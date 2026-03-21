import { createFileRoute, Outlet } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/tasks")({
  component: TasksLayout,
  head: () => ({
    meta: [{ title: "Tasks - ChemCrow2" }],
  }),
})

function TasksLayout() {
  return <Outlet />
}
