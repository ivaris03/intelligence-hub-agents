import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ChatComposer from './ChatComposer.vue'

const skills = [
  {
    id: 'skill-1',
    name: '简洁写作',
    description: '先给结论',
    instructions: '先给结论。',
    enabled: true,
    created_at: '2026-08-14T00:00:00Z',
    updated_at: '2026-08-14T00:00:00Z',
  },
  {
    id: 'skill-2',
    name: '风险检查',
    description: '补充风险',
    instructions: '补充风险。',
    enabled: true,
    created_at: '2026-08-14T00:00:00Z',
    updated_at: '2026-08-14T00:00:00Z',
  },
]

function mountComposer(mode: 'chat' | 'work' = 'work') {
  return mount(ChatComposer, {
    props: {
      modelValue: '',
      streaming: false,
      files: [],
      selectedFileIds: [],
      skills,
      selectedSkillIds: [],
      mode,
      agentType: 'image',
      modelName: 'qwen-plus',
      thinkingEffort: 'medium',
      uploadProgress: {},
    },
  })
}

describe('ChatComposer skill and agent selection', () => {
  it('selects multiple Skills in Work without @ labels and emits one Agent value', async () => {
    const wrapper = mountComposer()
    expect(wrapper.text()).not.toContain('@')

    await wrapper.get('.skill-select').trigger('click')
    expect(wrapper.text()).toContain('这里选择属于显式调用，会直接注入 System Prompt')
    expect(wrapper.text()).toContain('系统也可以根据任务自动调用已启用的 Skill')
    const options = wrapper.findAll('.skill-option')
    await options[0].trigger('click')
    await wrapper.setProps({ selectedSkillIds: ['skill-1'] })
    await options[1].trigger('click')

    expect(wrapper.emitted('update:selectedSkillIds')).toEqual([
      [['skill-1']],
      [['skill-1', 'skill-2']],
    ])

    await wrapper.get<HTMLSelectElement>('.composer-agent-select').setValue('slides')
    expect(wrapper.emitted('update:agentType')).toEqual([['slides']])
  })

  it('selects multiple Skills in Chat too', async () => {
    const wrapper = mountComposer('chat')
    await wrapper.get('.skill-select').trigger('click')
    await wrapper.findAll('.skill-option')[0].trigger('click')
    await wrapper.setProps({ selectedSkillIds: ['skill-1'] })
    await wrapper.findAll('.skill-option')[1].trigger('click')

    expect(wrapper.emitted('update:selectedSkillIds')).toEqual([
      [['skill-1']],
      [['skill-1', 'skill-2']],
    ])
  })

  it('turns the Work composer into a research topic dialogue entry', async () => {
    const wrapper = mountComposer()
    await wrapper.setProps({ agentType: 'research', topicDiscussion: true })

    expect(wrapper.get('textarea').attributes('placeholder')).toBe('继续讨论或修改研究主题…')
    expect(wrapper.find('.icon-button').exists()).toBe(false)
    expect(wrapper.find('.skill-select').exists()).toBe(false)
    expect(wrapper.find('.model-effort-control').exists()).toBe(false)

    await wrapper.get('textarea').setValue('把范围缩小到个人用户')
    await wrapper.setProps({ modelValue: '把范围缩小到个人用户' })
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('send')).toEqual([['把范围缩小到个人用户']])
  })
})
