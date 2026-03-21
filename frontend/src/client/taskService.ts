import type { CancelablePromise } from "./core/CancelablePromise"
import { OpenAPI } from "./core/OpenAPI"
import { request as __request } from "./core/request"
import type { TaskJobPublic, TaskJobsPublic } from "./taskTypes"

export class TasksService {
  public static listTasks(
    data: {
      skip?: number
      limit?: number
      status?: string
      task_type?: string
    } = {},
  ): CancelablePromise<TaskJobsPublic> {
    return __request(OpenAPI, {
      method: "GET",
      url: "/api/v1/tasks/",
      query: {
        skip: data.skip,
        limit: data.limit,
        status: data.status,
        task_type: data.task_type,
      },
      errors: { 422: "Validation Error" },
    })
  }

  public static getTask(data: {
    taskId: string
  }): CancelablePromise<TaskJobPublic> {
    return __request(OpenAPI, {
      method: "GET",
      url: "/api/v1/tasks/{task_id}",
      path: { task_id: data.taskId },
      errors: { 422: "Validation Error" },
    })
  }
}
