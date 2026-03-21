export type TaskJobPublic = {
  id: string
  user_id: string
  task_type: string
  status: string
  source: string
  conversation_id: string | null
  input_data: string
  result_data: string | null
  error: string | null
  celery_task_id: string | null
  created_at: string | null
  completed_at: string | null
}

export type TaskJobsPublic = {
  data: TaskJobPublic[]
  count: number
}
