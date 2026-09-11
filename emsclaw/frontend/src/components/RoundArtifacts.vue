<template>
  <div v-if="hasAny" class="flex flex-col gap-2.5 mt-1">
    <!-- 报告卡片区：本轮产物中的报告/交付物，直接可见，无需点开文件面板 -->
    <div v-if="reportFiles.length" class="flex flex-col gap-2">
      <div class="flex items-center gap-2 px-1">
        <div class="w-1.5 h-1.5 rounded-full bg-blue-500"></div>
        <span class="text-xs font-semibold text-[var(--text-secondary)] tracking-wide">{{ $t('Reports') }}</span>
        <span class="text-[10px] text-[var(--text-tertiary)] tabular-nums">({{ reportFiles.length }})</span>
      </div>

      <div
        v-for="file in reportFiles"
        :key="file.file_id"
        class="artifact-card group flex items-center gap-3 p-3 rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-[#1e1e1e] hover:border-blue-200 dark:hover:border-blue-800/60 hover:shadow-sm transition-all duration-200 cursor-pointer"
        @click="openFile(file)"
      >
        <div
          class="size-10 rounded-xl flex items-center justify-center flex-shrink-0 shadow-sm"
          :class="fileColor(file.filename)"
        >
          <component :is="fileType(file.filename).icon" class="size-5" />
        </div>
        <div class="flex flex-col flex-1 min-w-0">
          <div class="flex items-center gap-1.5 min-w-0">
            <span class="text-sm font-medium text-[var(--text-primary)] truncate group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
              {{ file.filename }}
            </span>
            <span class="flex-shrink-0 text-[10px] font-medium px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
              {{ $t('Report') }}
            </span>
          </div>
          <span class="text-xs text-[var(--text-tertiary)] mt-0.5">{{ formatFileSize(file.size) }}</span>
        </div>
        <div class="flex items-center gap-1 flex-shrink-0" @click.stop>
          <button
            v-if="isPreviewable(file.filename)"
            @click="openPreview(file)"
            class="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:bg-gray-50 dark:hover:bg-gray-800 hover:text-violet-500 hover:shadow-sm transition-all duration-200"
            :title="$t('Preview')"
          >
            <Eye class="size-4" />
          </button>
          <button
            @click="download(file)"
            class="p-1.5 rounded-lg text-[var(--text-tertiary)] hover:bg-gray-50 dark:hover:bg-gray-800 hover:text-blue-500 hover:shadow-sm transition-all duration-200"
            :title="$t('Download')"
          >
            <Download class="size-4" />
          </button>
        </div>
      </div>
    </div>

    <!-- 其他产物文件：折叠收纳，避免抢报告卡片视觉 -->
    <div v-if="otherFiles.length">
      <button
        class="flex items-center gap-1.5 px-1 py-1 rounded-lg text-xs text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors"
        @click="otherExpanded = !otherExpanded"
      >
        <ChevronRight class="size-3.5 transition-transform duration-200" :class="{ 'rotate-90': otherExpanded }" />
        <FolderOpen class="size-3.5" />
        <span>{{ $t('Other files') }}</span>
        <span class="tabular-nums">({{ otherFiles.length }})</span>
      </button>
      <Transition name="artifact-expand">
        <div v-if="otherExpanded" class="mt-1 space-y-0.5">
          <div
            v-for="file in otherFiles"
            :key="file.file_id"
            class="group flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-50/80 dark:hover:bg-white/5 transition-colors cursor-pointer"
            @click="openFile(file)"
          >
            <component :is="fileType(file.filename).icon" class="size-4 flex-shrink-0 text-[var(--text-tertiary)]" />
            <span class="text-xs text-[var(--text-secondary)] truncate flex-1 min-w-0">{{ file.filename }}</span>
            <span class="text-[10px] text-[var(--text-tertiary)] tabular-nums flex-shrink-0">{{ formatFileSize(file.size) }}</span>
            <button
              @click.stop="download(file)"
              class="p-1 rounded text-[var(--text-tertiary)] opacity-0 group-hover:opacity-100 hover:text-blue-500 transition-all flex-shrink-0"
              :title="$t('Download')"
            >
              <Download class="size-3.5" />
            </button>
          </div>
        </div>
      </Transition>
    </div>

    <FilePreviewModal :file="previewFile" :visible="previewVisible" @close="previewVisible = false" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { Download, Eye, ChevronRight, FolderOpen } from 'lucide-vue-next';
import type { RoundFileInfo } from '../types/event';
import type { FileInfo } from '../api/file';
import { triggerAuthenticatedDownload } from '../api/file';
import { getFileType, formatFileSize } from '../utils/fileType';
import FilePreviewModal from './FilePreviewModal.vue';

const props = defineProps<{
  files: RoundFileInfo[];
}>();

const PREVIEWABLE_EXTS = ['md', 'txt', 'log', 'csv', 'json', 'xml', 'yaml', 'yml', 'sh', 'py', 'js', 'ts', 'html', 'css', 'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp', 'ico'];

const otherExpanded = ref(false);
const previewFile = ref<FileInfo | null>(null);
const previewVisible = ref(false);

/**
 * 报告判定:优先用后端权威字段 `is_report`;历史会话的 round_files 里没有该字段
 * (该字段是后加的),回退到路径判据 `reports/`,避免老会话的报告落进折叠区。
 */
const isReport = (f: RoundFileInfo): boolean =>
  f.is_report ?? (f.relative_path || '').startsWith('reports/');

const reportFiles = computed(() => props.files.filter(f => isReport(f)));
const otherFiles = computed(() => props.files.filter(f => !isReport(f)));
const hasAny = computed(() => reportFiles.value.length > 0 || otherFiles.value.length > 0);


const fileType = (filename: string) => getFileType(filename);

const isPreviewable = (filename: string) => {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  return PREVIEWABLE_EXTS.includes(ext);
};

const fileColor = (filename: string) => {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  if (['py', 'js', 'ts', 'jsx', 'tsx', 'vue'].includes(ext)) return 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400';
  if (['md', 'txt', 'log', 'csv'].includes(ext)) return 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400';
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext)) return 'bg-violet-50 dark:bg-violet-900/20 text-violet-600 dark:text-violet-400';
  if (['pdf', 'doc', 'docx', 'ppt', 'pptx'].includes(ext)) return 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400';
  if (['json', 'xml', 'yaml', 'yml'].includes(ext)) return 'bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400';
  if (['html', 'css', 'scss'].includes(ext)) return 'bg-orange-50 dark:bg-orange-900/20 text-orange-600 dark:text-orange-400';
  if (['xls', 'xlsx'].includes(ext)) return 'bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400';
  return 'bg-gray-50 dark:bg-gray-800 text-gray-500 dark:text-gray-400';
};

const toFileInfo = (rf: RoundFileInfo): FileInfo => ({
  file_id: rf.file_id,
  filename: rf.filename,
  size: rf.size,
  upload_date: rf.upload_date,
  file_url: rf.file_url,
});

const openPreview = (file: RoundFileInfo) => {
  previewFile.value = toFileInfo(file);
  previewVisible.value = true;
};

/** 点卡片：可预览则弹预览，否则直接下载 */
const openFile = (file: RoundFileInfo) => {
  if (isPreviewable(file.filename)) openPreview(file);
  else download(file);
};

const download = async (file: RoundFileInfo) => {
  try {
    await triggerAuthenticatedDownload(toFileInfo(file));
  } catch (err) {
    console.error('Download failed:', err);
  }
};
</script>

<style scoped>
.artifact-card {
  animation: artifactSlideIn 0.25s ease-out both;
}
@keyframes artifactSlideIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

.artifact-expand-enter-active,
.artifact-expand-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}
.artifact-expand-enter-from,
.artifact-expand-leave-to {
  opacity: 0;
  max-height: 0;
}
.artifact-expand-enter-to,
.artifact-expand-leave-from {
  opacity: 1;
  max-height: 600px;
}
</style>
