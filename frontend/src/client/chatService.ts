/**
 * API service for conversations and messages.
 * Uses the same OpenAPI request helper as the generated client.
 * TODO: remove once the OpenAPI client is regenerated.
 */

import type { CancelablePromise } from "./core/CancelablePromise"
import { OpenAPI } from "./core/OpenAPI"
import { request as __request } from "./core/request"
import type {
  ChatMessageCreate,
  ChatMessagePublic,
  ChatMessagesPublic,
  ConversationCreate,
  ConversationPublic,
  ConversationsPublic,
  ConversationUpdate,
} from "./chatTypes"
import type { Message } from "./types.gen"

export class ConversationsService {
  public static listConversations(
    data: { skip?: number; limit?: number } = {},
  ): CancelablePromise<ConversationsPublic> {
    return __request(OpenAPI, {
      method: "GET",
      url: "/api/v1/conversations/",
      query: { skip: data.skip, limit: data.limit },
      errors: { 422: "Validation Error" },
    })
  }

  public static createConversation(data: {
    requestBody: ConversationCreate
  }): CancelablePromise<ConversationPublic> {
    return __request(OpenAPI, {
      method: "POST",
      url: "/api/v1/conversations/",
      body: data.requestBody,
      mediaType: "application/json",
      errors: { 422: "Validation Error" },
    })
  }

  public static getConversation(data: {
    conversationId: string
  }): CancelablePromise<ConversationPublic> {
    return __request(OpenAPI, {
      method: "GET",
      url: "/api/v1/conversations/{conversation_id}",
      path: { conversation_id: data.conversationId },
      errors: { 422: "Validation Error" },
    })
  }

  public static updateConversation(data: {
    conversationId: string
    requestBody: ConversationUpdate
  }): CancelablePromise<ConversationPublic> {
    return __request(OpenAPI, {
      method: "PATCH",
      url: "/api/v1/conversations/{conversation_id}",
      path: { conversation_id: data.conversationId },
      body: data.requestBody,
      mediaType: "application/json",
      errors: { 422: "Validation Error" },
    })
  }

  public static deleteConversation(data: {
    conversationId: string
  }): CancelablePromise<Message> {
    return __request(OpenAPI, {
      method: "DELETE",
      url: "/api/v1/conversations/{conversation_id}",
      path: { conversation_id: data.conversationId },
      errors: { 422: "Validation Error" },
    })
  }

  public static listMessages(data: {
    conversationId: string
    skip?: number
    limit?: number
  }): CancelablePromise<ChatMessagesPublic> {
    return __request(OpenAPI, {
      method: "GET",
      url: "/api/v1/conversations/{conversation_id}/messages",
      path: { conversation_id: data.conversationId },
      query: { skip: data.skip, limit: data.limit },
      errors: { 422: "Validation Error" },
    })
  }

  public static sendMessage(data: {
    conversationId: string
    requestBody: ChatMessageCreate
  }): CancelablePromise<ChatMessagePublic> {
    return __request(OpenAPI, {
      method: "POST",
      url: "/api/v1/conversations/{conversation_id}/messages",
      path: { conversation_id: data.conversationId },
      body: data.requestBody,
      mediaType: "application/json",
      errors: { 422: "Validation Error" },
    })
  }
}
