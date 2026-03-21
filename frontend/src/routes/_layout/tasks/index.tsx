import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  ListTodo,
} from "lucide-react"
import { useState } from "react"

import { TasksService } from "@/client/taskService"
import type { TaskJobPublic } from "@/client/taskTypes"
import { columns } from "@/components/Tasks/columns"
import PendingTasks from "@/components/Pending/PendingTasks"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table"

const PAGE_SIZE = 20

export const Route = createFileRoute("/_layout/tasks/")({
  component: TasksIndex,
})

function TasksIndex() {
  const [page, setPage] = useState(0)

  const { data, isLoading } = useQuery({
    queryKey: ["tasks", page],
    queryFn: () =>
      TasksService.listTasks({ skip: page * PAGE_SIZE, limit: PAGE_SIZE }),
  })

  const tasks: TaskJobPublic[] = data?.data ?? []
  const totalCount = data?.count ?? 0
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))

  const table = useReactTable({
    data: tasks,
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Tasks</h1>
        <p className="text-muted-foreground">View and track your tasks</p>
      </div>

      {isLoading ? (
        <PendingTasks />
      ) : totalCount === 0 ? (
        <div className="flex flex-col items-center justify-center text-center py-12">
          <div className="rounded-full bg-muted p-4 mb-4">
            <ListTodo className="h-8 w-8 text-muted-foreground" />
          </div>
          <h3 className="text-lg font-semibold">No tasks yet</h3>
          <p className="text-muted-foreground">
            Tasks will appear here when you use tools from the chat or run them
            manually
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow
                  key={headerGroup.id}
                  className="hover:bg-transparent"
                >
                  {headerGroup.headers.map((header) => (
                    <TableHead key={header.id}>
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {totalPages > 1 && (
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-4 border-t bg-muted/20">
              <div className="text-sm text-muted-foreground">
                Showing {page * PAGE_SIZE + 1} to{" "}
                {Math.min((page + 1) * PAGE_SIZE, totalCount)} of{" "}
                <span className="font-medium text-foreground">
                  {totalCount}
                </span>{" "}
                tasks
              </div>

              <div className="flex items-center gap-x-6">
                <div className="flex items-center gap-x-1 text-sm text-muted-foreground">
                  <span>Page</span>
                  <span className="font-medium text-foreground">
                    {page + 1}
                  </span>
                  <span>of</span>
                  <span className="font-medium text-foreground">
                    {totalPages}
                  </span>
                </div>
                <div className="flex items-center gap-x-1">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 w-8 p-0"
                    onClick={() => setPage(0)}
                    disabled={page === 0}
                  >
                    <span className="sr-only">First page</span>
                    <ChevronsLeft className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 w-8 p-0"
                    onClick={() => setPage((p) => p - 1)}
                    disabled={page === 0}
                  >
                    <span className="sr-only">Previous page</span>
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 w-8 p-0"
                    onClick={() => setPage((p) => p + 1)}
                    disabled={page >= totalPages - 1}
                  >
                    <span className="sr-only">Next page</span>
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 w-8 p-0"
                    onClick={() => setPage(totalPages - 1)}
                    disabled={page >= totalPages - 1}
                  >
                    <span className="sr-only">Last page</span>
                    <ChevronsRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
