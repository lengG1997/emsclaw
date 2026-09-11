<template>
  <SimpleBar>
    <div
      class="flex flex-col h-full flex-1 min-w-0 mx-auto w-full sm:min-w-[390px] px-5 justify-center items-start gap-2 relative max-w-full sm:max-w-full">
      <div class="w-full pt-4 pb-4 px-5 bg-[var(--background-gray-main)] sticky top-0 z-10 mx-[-1.25]">
        <div class="flex justify-between items-center w-full absolute left-0 right-0">
          <div class="h-8 relative z-20 overflow-hidden flex gap-2 items-center flex-shrink-0">
            <div class="relative flex items-center">
            </div>
            <div class="flex items-center gap-2">
              <div class="w-[30px] h-[30px]">
                 <RobotAvatar :interactive="false" />
              </div>
              <EmsClawLogoTextIcon />
            </div>
          </div>
          <div class="flex items-center gap-2">
            <LanguageSelector />
            <div class="relative flex items-center" aria-expanded="false" aria-haspopup="dialog"
              @mouseenter="handleUserMenuEnter" @mouseleave="handleUserMenuLeave">
              <div class="relative flex items-center justify-center font-bold cursor-pointer flex-shrink-0">
                <div
                  class="relative flex items-center justify-center font-bold flex-shrink-0 rounded-full overflow-hidden"
                  style="width: 32px; height: 32px; font-size: 16px; color: rgba(255, 255, 255, 0.9); background-color: rgb(59, 130, 246);">
                  {{ avatarLetter }}</div>
              </div>
              <!-- User Menu -->
              <div v-if="showUserMenu" @mouseenter="handleUserMenuEnter" @mouseleave="handleUserMenuLeave"
                class="absolute top-full right-0 mt-1 mr-[-15px] z-50">
                <UserMenu />
              </div>
            </div>
          </div>
        </div>
        <div class="h-8"></div>
      </div>
      <div class="w-full max-w-full sm:max-w-[768px] sm:min-w-[390px] mx-auto mt-[120px] mb-auto">
        <!-- Welcome Area -->
        <div class="welcome-area w-full flex flex-col items-center justify-center pb-6">
          <div class="size-14 rounded-2xl bg-gradient-to-br from-blue-500 via-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20 mb-4">
            <svg class="size-7 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" /></svg>
          </div>
          <h1 class="text-2xl font-bold text-[var(--text-primary)] text-center">
            {{ fullGreeting }}
          </h1>
          <p class="text-sm text-[var(--text-tertiary)] mt-1 typewriter-line">
            <span
              v-for="(char, i) in displayedChars"
              :key="`${typingCycle}-${i}`"
              class="typewriter-char"
              :class="{ 'typewriter-space': char === ' ' }"
              :style="{ '--char-index': i }"
            >{{ char }}</span><span class="typewriter-cursor" :class="{ 'typing-active': isTyping }"></span>
          </p>
        </div>

        <!-- Quick Action Cards -->
        <QuickActionCards @select="usePrompt" class="mb-5" />

        <!-- ChatBox -->
        <div class="flex flex-col gap-1 w-full">
          <div class="flex flex-col bg-[var(--background-gray-main)] w-full">
            <div class="[&amp;:not(:empty)]:pb-2 bg-[var(--background-gray-main)] rounded-[22px_22px_0px_0px]"></div>
            <ChatBox 
              ref="chatBoxRef"
              :rows="2" 
              v-model="message" 
              @submit="handleSubmit" 
              :isRunning="isSubmitting" 
              :attachments="attachments"
              :models="models"
              :selectedModelId="selectedModelId"
              @update:selectedModelId="selectedModelId = $event"
              @open-model-settings="openSettingsDialog('models')"
            />
          </div>
        </div>
      </div>
    </div>
  </SimpleBar>
</template>

<script setup lang="ts">
import SimpleBar from '../components/SimpleBar.vue';
import { ref, onMounted, onUnmounted, computed, watch } from 'vue';
import { useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import ChatBox from '../components/ChatBox.vue';
import { createSession } from '../api/agent';
import { listModels, type ModelConfig } from '../api/models';
import { showErrorToast } from '../utils/toast';
import EmsClawLogoTextIcon from '../components/icons/EmsClawLogoTextIcon.vue';
import RobotAvatar from '../components/icons/RobotAvatar.vue';
import type { FileInfo } from '../api/file';
import { useFilePanel } from '../composables/useFilePanel';
import { setPendingChat } from '../composables/usePendingChat';
import { useAuth } from '../composables/useAuth';
import { useSettingsDialog } from '../composables/useSettingsDialog';
import UserMenu from '../components/UserMenu.vue';
import QuickActionCards from '../components/QuickActionCards.vue';
import LanguageSelector from '@/components/LanguageSelector.vue';
import { DEFAULT_MODE } from '../constants/agentModes';

const { t } = useI18n();
const router = useRouter();
const { currentUser } = useAuth();
const message = ref('');

// ── Typewriter effect ──
const displayedChars = ref<string[]>([]);
const typingCycle = ref(0);
const isTyping = ref(false);
const currentSubtitleIdx = ref(0);
let typeTimer: ReturnType<typeof setTimeout> | null = null;

// 静态问候语
const fullGreeting = computed(() => {
  const name = currentUser.value?.fullname || 'User';
  return `${t('Hello')}, ${name}`;
});

// 打字机效果循环显示的副标题
const subtitleTemplates = computed(() => [
  t('home_subtitle_1'),
  t('home_subtitle_2'),
  t('home_subtitle_3'),
  t('home_subtitle_4'),
]);

const currentSubtitle = computed(() => subtitleTemplates.value[currentSubtitleIdx.value]);

function clearTimer() {
  if (typeTimer) { clearTimeout(typeTimer); typeTimer = null; }
}

function startTyping() {
  const text = currentSubtitle.value;
  let idx = 0;
  displayedChars.value = [];
  isTyping.value = true;

  const typeNext = () => {
    if (idx < text.length) {
      displayedChars.value = [...displayedChars.value, text[idx]];
      idx++;
      // 随机延迟让打字效果更自然
      typeTimer = setTimeout(typeNext, 90 + Math.random() * 60);
    } else {
      isTyping.value = false;
      typeTimer = setTimeout(startErasing, 3000);
    }
  };
  typeNext();
}

function startErasing() {
  isTyping.value = true;
  const eraseNext = () => {
    if (displayedChars.value.length > 0) {
      displayedChars.value = displayedChars.value.slice(0, -1);
      typeTimer = setTimeout(eraseNext, 35);
    } else {
      currentSubtitleIdx.value = (currentSubtitleIdx.value + 1) % subtitleTemplates.value.length;
      typingCycle.value++;
      typeTimer = setTimeout(startTyping, 400);
    }
  };
  eraseNext();
}

const usePrompt = (query: string) => { message.value = query; };
const isSubmitting = ref(false);
const attachments = ref<FileInfo[]>([]);
const chatBoxRef = ref<InstanceType<typeof ChatBox> | null>(null);
const { hideFilePanel } = useFilePanel();
const { isSettingsDialogOpen, openSettingsDialog } = useSettingsDialog();

const models = ref<ModelConfig[]>([]);
const selectedModelId = ref<string | null>(null);

const avatarLetter = computed(() => {
  return currentUser.value?.fullname?.charAt(0)?.toUpperCase() || 'M';
});

const showUserMenu = ref(false);
const userMenuTimeout = ref<ReturnType<typeof setTimeout> | null>(null);

const handleUserMenuEnter = () => {
  if (userMenuTimeout.value) {
    clearTimeout(userMenuTimeout.value);
    userMenuTimeout.value = null;
  }
  showUserMenu.value = true;
};

const handleUserMenuLeave = () => {
  userMenuTimeout.value = setTimeout(() => {
    showUserMenu.value = false;
  }, 200);
};

onMounted(async () => {
  hideFilePanel();
  startTyping(); // 启动打字机效果
  const modelsData = await listModels().catch(err => {
    console.error("Failed to load models", err);
    return [];
  });
  models.value = modelsData;

  if (models.value.length === 0) {
    openSettingsDialog('models');
  } else {
    const sys = models.value.find(m => m.is_system);
    if (sys) selectedModelId.value = sys.id;
    else if (models.value.length > 0) selectedModelId.value = models.value[0].id;
  }
})

onUnmounted(() => {
  clearTimer(); // 组件卸载时清理定时器
})

watch(isSettingsDialogOpen, async (newVal, oldVal) => {
  if (oldVal === true && newVal === false) {
    try {
      const modelsData = await listModels();
      models.value = modelsData;
      if (!selectedModelId.value || !modelsData.find(m => m.id === selectedModelId.value)) {
        const sys = modelsData.find(m => m.is_system);
        selectedModelId.value = sys ? sys.id : (modelsData.length > 0 ? modelsData[0].id : null);
      }
    } catch (err) {
      console.error("Failed to refresh models after settings change", err);
    }
  }
});

const handleSubmit = async () => {
  if (!message.value.trim() || isSubmitting.value) return;
  isSubmitting.value = true;

  try {
    // Step 1: Create session
    const session = await createSession({
      mode: DEFAULT_MODE,
      model_config_id: selectedModelId.value || undefined
    });
    const sessionId = session.session_id;

    // Step 2: Upload any local files (kept in browser memory until now)
    let uploadedFiles: FileInfo[] = [];
    if (chatBoxRef.value) {
      uploadedFiles = await chatBoxRef.value.uploadPendingFiles(sessionId);
    }

    // Step 3: Store pending data and navigate
    setPendingChat({
      message: message.value,
      files: uploadedFiles,
      mode: DEFAULT_MODE,
      selectedModelId: selectedModelId.value
    });
    router.push(`/chat/${sessionId}`);
  } catch (error) {
    console.error('Failed to create session:', error);
    showErrorToast(t('Failed to create session, please try again later'));
    isSubmitting.value = false;
  }
};
</script>

<style scoped>
.welcome-area { animation: fadeInUp 0.5s ease-out; }
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Typewriter effect styles */
.typewriter-line {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 1.5em;
}

.typewriter-char {
  display: inline-block;
  animation: charFadeIn 0.2s ease-out forwards;
}

.typewriter-space {
  width: 0.3em;
}

.typewriter-cursor {
  display: inline-block;
  width: 3px;
  height: 1.1em;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  margin-left: 0;
  border-radius: 2px;
  animation: cursorBlink 1s ease-in-out infinite;
}

.typewriter-cursor.typing-active {
  animation: cursorBlink 0.5s ease-in-out infinite;
}

@keyframes charFadeIn {
  0% {
    opacity: 0;
    transform: translateY(2px);
  }
  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes cursorBlink {
  0%, 45% { opacity: 1; }
  50%, 95% { opacity: 0; }
  100% { opacity: 1; }
}
</style>
