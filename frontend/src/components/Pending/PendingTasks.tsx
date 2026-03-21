import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const PendingTasks = () => (
  <Table>
    <TableHeader>
      <TableRow>
        <TableHead>Status</TableHead>
        <TableHead>Tool</TableHead>
        <TableHead>Source</TableHead>
        <TableHead>Created</TableHead>
        <TableHead>
          <span className="sr-only">Result</span>
        </TableHead>
      </TableRow>
    </TableHeader>
    <TableBody>
      {Array.from({ length: 5 }).map((_, index) => (
        <TableRow key={index}>
          <TableCell>
            <Skeleton className="h-5 w-20 rounded-full" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-5 w-28 rounded-full" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-4 w-16" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-4 w-16" />
          </TableCell>
          <TableCell>
            <div className="flex justify-end">
              <Skeleton className="h-7 w-20 rounded-md" />
            </div>
          </TableCell>
        </TableRow>
      ))}
    </TableBody>
  </Table>
)

export default PendingTasks
