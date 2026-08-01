import { ref } from 'vue'

export const currentTab = ref('video')

export function go(tab) {
  currentTab.value = tab
}
