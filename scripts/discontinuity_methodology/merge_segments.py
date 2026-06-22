"""Allege 2025.geojson :
  1) drop TVr < 100
  2) merge chaines de segments consecutifs meme dir / meme FC/RAMP/ROUND / TVr +/- 5%
     -> moyenne ponderee par longueur sur tous les attributs numeriques
     -> first/composite sur categorical
Sortie : 2025_light.geojson, source intacte.
"""
from __future__ import annotations
import os
import time
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge

# External data root — override via MDL_DATA_ROOT env var.
DATA_ROOT = Path(os.environ.get("MDL_DATA_ROOT", Path.home() / "mdl-data"))
SRC = DATA_ROOT / 'Travaux_Python' / 'Travaux_donnees_Lyon' / 'Livrables' / '2025.geojson'
DST = DATA_ROOT / 'Travaux_Python' / 'Travaux_donnees_Lyon' / 'Livrables' / '2025_light.geojson'
TVR_MIN = 100.0
TOL = 0.05  # 5%

KEEP_FIRST = {'agregId', 'FC', 'FUNC_CLASS', 'RAMP', 'ROUNDABOUT', 'DD'}
NEVER_AGGREGATE = {'agregId', 'FC', 'FUNC_CLASS', 'RAMP', 'ROUNDABOUT', 'DD',
                   'REF_IN_ID', 'NREF_IN_ID', 'geometry'}


def main() -> int:
    t0 = time.time()
    print(f'Loading {SRC.name} ...')
    gdf = gpd.read_file(SRC, engine='pyogrio')
    n_in = len(gdf)
    print(f'  {n_in:,} rows x {len(gdf.columns)} cols')

    # 1) Filter TVr
    before = len(gdf)
    gdf = gdf[gdf['TVr'] >= TVR_MIN].copy().reset_index(drop=True)
    print(f'\nAfter TVr >= {TVR_MIN:g}: {len(gdf):,} ({100*len(gdf)/before:.1f}% kept)')

    # 2) dir_class, in_node, out_node, base_id
    aid = gdf['agregId'].astype(str)
    gdf['dir_class'] = np.where(aid.str.endswith('-F'), 'F',
                       np.where(aid.str.endswith('-T'), 'T', 'O'))
    gdf['base_id'] = aid.str.replace(r'-[FT]$', '', regex=True)
    gdf['in_node']  = np.where(gdf['dir_class'] == 'T', gdf['NREF_IN_ID'], gdf['REF_IN_ID']).astype('int64')
    gdf['out_node'] = np.where(gdf['dir_class'] == 'T', gdf['REF_IN_ID'], gdf['NREF_IN_ID']).astype('int64')

    # length in meters (Lambert-93)
    print('Computing lengths (Lambert-93)...')
    gdf['length_m'] = gdf.to_crs('EPSG:2154').geometry.length

    # 3) Relays per direction class
    print('Identifying relay nodes (per direction)...')
    relays = {}
    for dc in ('F', 'T', 'O'):
        sub = gdf[gdf['dir_class'] == dc]
        arriving = sub.groupby('out_node').size()  # edges arriving at node
        leaving  = sub.groupby('in_node').size()    # edges leaving from node
        relays[dc] = set(arriving[arriving == 1].index) & set(leaving[leaving == 1].index)
        print(f'  dir={dc}  n_edges={len(sub):,}  relay_nodes={len(relays[dc]):,}')

    # 4) Successor (edge A -> edge B) via merge
    print('Building successors...')
    left = gdf[['dir_class', 'out_node', 'FC', 'RAMP', 'ROUNDABOUT', 'TVr', 'base_id']].copy()
    left.columns = ['dir_class', 'on', 'FCa', 'Ra', 'ROa', 'TVa', 'bidA']
    left['ia'] = left.index
    right = gdf[['dir_class', 'in_node', 'FC', 'RAMP', 'ROUNDABOUT', 'TVr', 'base_id']].copy()
    right.columns = ['dir_class', 'inb', 'FCb', 'Rb', 'ROb', 'TVb', 'bidB']
    right['ib'] = right.index

    pairs = left.merge(right, left_on=['dir_class', 'on'], right_on=['dir_class', 'inb'])
    print(f'  {len(pairs):,} raw connected pairs')

    # Filters
    same_attrs = (pairs['FCa'] == pairs['FCb']) & (pairs['Ra'] == pairs['Rb']) & (pairs['ROa'] == pairs['ROb'])
    pairs = pairs[same_attrs]
    print(f'  {len(pairs):,} after same-FC/RAMP/ROUND')

    not_uturn = pairs['bidA'] != pairs['bidB']
    pairs = pairs[not_uturn]
    print(f'  {len(pairs):,} after anti-U-turn')

    tvmin = np.minimum(pairs['TVa'].values, pairs['TVb'].values)
    tvmax = np.maximum(pairs['TVa'].values, pairs['TVb'].values)
    within = (tvmax - tvmin) / np.where(tvmax > 0, tvmax, 1) <= TOL
    pairs = pairs[within]
    print(f'  {len(pairs):,} after TVr +/- {TOL*100:.0f}%')

    is_relay = [n in relays[d] for n, d in zip(pairs['on'].values, pairs['dir_class'].values)]
    pairs = pairs[is_relay]
    print(f'  {len(pairs):,} after relay-node filter -> mergeable successor pairs')

    succ = dict(zip(pairs['ia'].astype(int), pairs['ib'].astype(int)))
    pred = dict(zip(pairs['ib'].astype(int), pairs['ia'].astype(int)))

    # 5) Walk chains from heads (edges with no valid predecessor)
    print('Walking chains...')
    heads = [i for i in gdf.index.astype(int) if i not in pred]
    visited: set[int] = set()
    chains: list[list[int]] = []
    for h in heads:
        if h in visited:
            continue
        chain = [h]
        visited.add(h)
        cur = h
        while True:
            nxt = succ.get(cur)
            if nxt is None or nxt in visited:
                break
            chain.append(nxt)
            visited.add(nxt)
            cur = nxt
        chains.append(chain)
    # safety: anything in cycles (rare) -> singletons
    for i in gdf.index.astype(int):
        if i not in visited:
            chains.append([i])
            visited.add(i)
    n_singletons = sum(1 for c in chains if len(c) == 1)
    n_merged_chains = sum(1 for c in chains if len(c) > 1)
    max_chain = max(len(c) for c in chains)
    print(f'  total chains: {len(chains):,}')
    print(f'    singletons: {n_singletons:,}')
    print(f'    merged    : {n_merged_chains:,}  (avg {(len(gdf)-n_singletons)/max(n_merged_chains,1):.1f} segs, max {max_chain})')

    # 6) Aggregate
    print('Aggregating chains...')
    numeric_cols = [c for c in gdf.columns
                    if c not in NEVER_AGGREGATE and pd.api.types.is_numeric_dtype(gdf[c])]

    out_rows = []
    for chain in chains:
        sub = gdf.loc[chain]
        if len(sub) == 1:
            row = sub.iloc[0].to_dict()
            row['n_merged'] = 1
            # ensure length_m kept
            row['length_m'] = float(row.get('length_m', 0.0))
            out_rows.append(row)
        else:
            total_len = float(sub['length_m'].sum())
            w = (sub['length_m'].values / total_len)
            merged = {}
            # numerics: weighted mean
            for col in numeric_cols:
                merged[col] = float((sub[col].astype(float).values * w).sum())
            # categorical: keep first (verified same by merge criteria)
            for col in KEEP_FIRST:
                if col in sub.columns:
                    merged[col] = sub[col].iloc[0]
            # IDs: composite agregId, first REF, last NREF (in chain order = flow order)
            merged['agregId'] = "+".join(sub['agregId'].astype(str).tolist())
            merged['REF_IN_ID']  = int(sub.iloc[0]['REF_IN_ID'])
            merged['NREF_IN_ID'] = int(sub.iloc[-1]['NREF_IN_ID'])
            # geometry: merge
            try:
                geom = linemerge(MultiLineString(sub.geometry.tolist()))
                if geom.geom_type == 'MultiLineString':
                    # fallback if not perfectly connected
                    coords = []
                    for g in sub.geometry:
                        if coords:
                            coords.extend(list(g.coords)[1:])
                        else:
                            coords.extend(list(g.coords))
                    geom = LineString(coords)
            except Exception:
                coords = []
                for g in sub.geometry:
                    if coords:
                        coords.extend(list(g.coords)[1:])
                    else:
                        coords.extend(list(g.coords))
                geom = LineString(coords)
            merged['geometry'] = geom
            merged['length_m'] = total_len
            merged['n_merged'] = len(sub)
            out_rows.append(merged)

    out_gdf = gpd.GeoDataFrame(out_rows, geometry='geometry', crs=gdf.crs)
    # drop internal helper cols
    for c in ('dir_class', 'base_id', 'in_node', 'out_node'):
        if c in out_gdf.columns:
            out_gdf = out_gdf.drop(columns=[c])

    n_out = len(out_gdf)
    print(f'\nResult: {n_out:,} features (vs {n_in:,} original)')
    print(f'  Reduction: {100 * (1 - n_out/n_in):.1f}%')

    # Stats merge
    merged_counts = out_gdf['n_merged']
    print(f'  Segments mergees moyennes/chain : {merged_counts.mean():.2f}')
    print(f'  Plus longue chaine             : {merged_counts.max()}')

    # 7) Export
    print(f'\nWriting {DST.name} ...')
    out_gdf.to_file(DST, driver='GeoJSON', engine='pyogrio')
    sz_mb = DST.stat().st_size / 1024 / 1024
    src_mb = SRC.stat().st_size / 1024 / 1024
    print(f'  -> {sz_mb:.1f} MB  (source = {src_mb:.0f} MB, reduction {100*(1-sz_mb/src_mb):.1f}%)')
    print(f'\nTotal: {time.time()-t0:.1f}s')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
