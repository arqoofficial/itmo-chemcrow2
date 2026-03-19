import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate, useParams } from "@tanstack/react-router"

import { ConversationsService } from "@/client/chatService"
import type { ConversationPublic } from "@/client/chatTypes"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

interface DeleteChatDialogProps {
  conversation: ConversationPublic | null
  onClose: () => void
}

export function DeleteChatDialog({
  conversation,
  onClose,
}: DeleteChatDialogProps) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const params = useParams({ strict: false })
  const activeId = (params as Record<string, string | undefined>)
    .conversationId

  const mutation = useMutation({
    mutationFn: () =>
      ConversationsService.deleteConversation({
        conversationId: conversation!.id,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] })
      onClose()
      if (activeId === conversation?.id) {
        navigate({ to: "/chat" })
      }
    },
  })

  return (
    <Dialog open={!!conversation} onOpenChange={() => onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Удалить диалог?</DialogTitle>
          <DialogDescription>
            Диалог «{conversation?.title}» и все сообщения будут удалены
            безвозвратно.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Отмена
          </Button>
          <Button
            variant="destructive"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? "Удаляю…" : "Удалить"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
