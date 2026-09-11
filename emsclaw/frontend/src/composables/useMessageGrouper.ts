import { computed, Ref, unref } from 'vue';
import { Message, MessageContent } from '../types/message';
import type { StatisticsData, RoundFileInfo } from '../types/event';

export interface GroupedMessage {
  type: 'single' | 'process';
  message?: Message;
  messages?: Message[];
  id: string;
}

export function useMessageGrouper(messagesRef: Ref<Message[]> | Message[]) {
  const groupedMessages = computed<GroupedMessage[]>(() => {
    const messages = unref(messagesRef);
    const groups: GroupedMessage[] = [];
    let currentProcessGroup: Message[] = [];
    let currentAssistantGroup: Message[] = [];

    let processGroupCounter = 0;
    let assistantGroupCounter = 0;

    const flushProcessGroup = () => {
      if (currentProcessGroup.length > 0) {
        const firstIdx = messages.indexOf(currentProcessGroup[0]);
        groups.push({
          type: 'process',
          messages: [...currentProcessGroup],
          id: `process-${firstIdx}-${processGroupCounter++}`
        });
        currentProcessGroup = [];
      }
    };

    const flushAssistantGroup = () => {
      if (currentAssistantGroup.length > 0) {
        const firstMsg = currentAssistantGroup[0];
        const firstIdx = messages.indexOf(currentAssistantGroup[0]);
        const mergedContent = currentAssistantGroup
          .map(m => (m.content as any).content || '')
          .join('\n\n');

        // 一轮对话可能由多条 assistant 消息组成（例：最终回复 + 后端在 done 前
        // 追加的调度预览块）。`done` 事件会把 statistics / round_files 挂到**最后
        // 一条** assistant 上，而合并只取第一条的字段会导致它们被丢掉。
        // 统一从整组里取最后一个非空值，保证统计信息与本轮文件不丢。
        let statistics: StatisticsData | undefined;
        let roundFiles: RoundFileInfo[] | undefined;
        for (const m of currentAssistantGroup) {
          const c = m.content as MessageContent;
          if (c?.statistics && Object.keys(c.statistics).length > 0) {
            statistics = c.statistics;
          }
          if (c?.round_files?.length) {
            roundFiles = c.round_files;
          }
        }

        const mergedMsg: Message = {
          ...firstMsg,
          content: {
            ...firstMsg.content,
            content: mergedContent,
            ...(statistics ? { statistics } : {}),
            ...(roundFiles ? { round_files: roundFiles } : {}),
          } as any
        };

        groups.push({
          type: 'single',
          message: mergedMsg,
          id: `merged-assistant-${firstIdx}-${assistantGroupCounter++}`
        });
        currentAssistantGroup = [];
      }
    };

    messages.forEach((msg, index) => {
      if (msg.type === 'step' || msg.type === 'tool') {
        flushAssistantGroup();
        currentProcessGroup.push(msg);
      } else if (msg.type === 'assistant') {
        flushProcessGroup();
        currentAssistantGroup.push(msg);
      } else {
        flushProcessGroup();
        flushAssistantGroup();
        groups.push({
          type: 'single',
          message: msg,
          id: `msg-${index}`
        });
      }
    });

    flushProcessGroup();
    flushAssistantGroup();
    return groups;
  });

  return {
    groupedMessages
  };
}
