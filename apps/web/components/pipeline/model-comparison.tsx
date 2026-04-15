"use client";

import { useMemo, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { motion } from "framer-motion";
import { ArrowUpDown, Eye, CheckCircle2, Trophy } from "lucide-react";
import { cn } from "@/lib/utils";
import { NeonButton } from "@/components/ui/neon-button";

export interface ModelResult {
  id: string;
  name: string;
  architecture: string;
  activation: string;
  lr: number;
  epochs: number;
  trainLoss: number;
  valLoss: number;
  r2: number;
  mape: number;
  gehPct: number;
  isBest?: boolean;
}

interface ModelComparisonProps {
  models: ModelResult[];
  onView: (model: ModelResult) => void;
  onSelect: (model: ModelResult) => void;
}

export function ModelComparison({
  models,
  onView,
  onSelect,
}: ModelComparisonProps) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "valLoss", desc: false },
  ]);

  const columns = useMemo<ColumnDef<ModelResult>[]>(
    () => [
      {
        id: "rank",
        header: "#",
        cell: ({ row }) => {
          const isBest = row.original.isBest;
          return (
            <div className="flex items-center justify-center">
              {isBest ? (
                <Trophy size={14} className="text-yellow-400" />
              ) : (
                <span className="text-xs text-muted">{row.index + 1}</span>
              )}
            </div>
          );
        },
        size: 40,
      },
      {
        accessorKey: "name",
        header: "Modele",
        cell: ({ row }) => (
          <span
            className={cn(
              "text-xs font-medium",
              row.original.isBest ? "text-yellow-400" : "text-foreground"
            )}
          >
            {row.original.name}
          </span>
        ),
      },
      {
        accessorKey: "architecture",
        header: "Architecture",
        cell: ({ getValue }) => (
          <span className="text-xs text-muted font-mono">
            {getValue<string>()}
          </span>
        ),
      },
      {
        accessorKey: "valLoss",
        header: ({ column }) => (
          <button
            type="button"
            className="flex items-center gap-1 text-xs"
            onClick={() => column.toggleSorting()}
          >
            Val Loss <ArrowUpDown size={12} />
          </button>
        ),
        cell: ({ getValue }) => (
          <span className="text-xs font-mono text-cyan">
            {getValue<number>().toFixed(6)}
          </span>
        ),
      },
      {
        accessorKey: "r2",
        header: ({ column }) => (
          <button
            type="button"
            className="flex items-center gap-1 text-xs"
            onClick={() => column.toggleSorting()}
          >
            R2 <ArrowUpDown size={12} />
          </button>
        ),
        cell: ({ getValue }) => (
          <span className="text-xs font-mono">{getValue<number>().toFixed(4)}</span>
        ),
      },
      {
        accessorKey: "mape",
        header: "MAPE %",
        cell: ({ getValue }) => (
          <span className="text-xs font-mono">{getValue<number>().toFixed(1)}</span>
        ),
      },
      {
        accessorKey: "gehPct",
        header: "GEH<5 %",
        cell: ({ getValue }) => {
          const v = getValue<number>();
          return (
            <span
              className={cn(
                "text-xs font-mono",
                v >= 85 ? "text-emerald-400" : v >= 70 ? "text-yellow-400" : "text-red-400"
              )}
            >
              {v.toFixed(1)}
            </span>
          );
        },
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }) => (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => onView(row.original)}
              className="p-1.5 rounded-lg hover:bg-surface-light text-muted hover:text-accent transition-colors"
              title="Voir le detail"
            >
              <Eye size={14} />
            </button>
            <button
              type="button"
              onClick={() => onSelect(row.original)}
              className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-muted hover:text-emerald-400 transition-colors"
              title="Choisir ce modele"
            >
              <CheckCircle2 size={14} />
            </button>
          </div>
        ),
        size: 80,
      },
    ],
    [onView, onSelect]
  );

  const table = useReactTable({
    data: models,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="glass overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b border-border">
                {hg.headers.map((header) => (
                  <th
                    key={header.id}
                    className="px-3 py-2.5 text-left text-xs font-medium text-muted"
                    style={{ width: header.getSize() }}
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row, idx) => (
              <motion.tr
                key={row.id}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.03 }}
                className={cn(
                  "border-b border-border/50 hover:bg-surface-light/30 transition-colors",
                  row.original.isBest && "bg-yellow-400/5 neon-glow"
                )}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-2.5">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </motion.tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
