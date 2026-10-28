// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, expect, it, vi } from 'vitest';

const capture = vi.hoisted(() => ({ previewArgs: null, executeBody: null, t: key => key }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: capture.t, i18n: { language: 'en' } }) }));
vi.mock('@/service/api.js', async importOriginal => {
    const actual = await importOriginal();
    return {
        ...Object.fromEntries(Object.keys(actual).map(key => [key, vi.fn().mockResolvedValue({ status: 'success', data: [] })])),
        getAgentCards: vi.fn().mockResolvedValue({ data: [{ name: 'Host' }] }),
        matchWorkflowsTopN: vi.fn().mockResolvedValue([
            { workflow_id: 'wf-role', name: 'Role flow', description: 'd', binding: 'role' },
            { workflow_id: 'wf-inst', name: 'Instance flow', description: 'd', binding: 'instance' },
        ]),
        previewRoleExecution: vi.fn().mockImplementation(async args => {
            capture.previewArgs = args;
            const overridden = Object.keys(args.task_overrides || {}).length > 0
                || Object.keys(args.group_overrides || {}).length > 0;
            return {
                psop_id: args.psop_id, psop_name: 'Role flow', template_fingerprint: 'a'.repeat(64),
                catalog_version: 'cat-v1', config_version: 'cfg-v1', policy_version: 'policy-v1',
                execution_scope: 't/city-a/b', caller_id: 'fixture-admin',
                units: [{
                    unit_id: 'task:t1', binding_group: null, task_ids: ['t1'],
                    required_skills: [{ task_id: 't1', role_id: 'r', role_version: '1', skill_id: 's' }],
                    current_selection: {
                        instance_id: 'inst-a', agent_name: 'A', priority: 10,
                        selection_reason: overridden ? 'explicit_override' : 'highest_priority',
                    },
                    candidates: [{ instance_id: 'inst-a', agent_name: 'A', priority: 10 }],
                    exclusions: [{ instance_id: 'inst-b', reasons: ['OUT_OF_SCOPE'] }],
                }],
                issues: [], can_execute: true, resolution_fingerprint: 'b'.repeat(64),
            };
        }),
    };
});
vi.mock('@/service/roleStream.js', () => ({
    streamRoleExecution: vi.fn(async (body, handlers) => {
        capture.executeBody = body;
        handlers?.onDone?.();
    }),
}));
vi.mock('../orchestration_center/workflow/index.jsx', () => ({ default: () => null }));
vi.mock('./execution_statistics/index.jsx', () => ({ default: () => null }));

import ExecutionCenter from './index.jsx';

const render = async () => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);
    vi.stubGlobal('EventSource', class {
        static CLOSED = 2;
        constructor() { this.readyState = 1; }
        close() { this.readyState = 2; }
    });
    const scroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollTo');
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() });
    await act(async () => root.render(<ExecutionCenter isDark={false} />));
    return { container, root, scroll };
};

const teardown = async (root, container, scroll) => {
    await act(async () => root.unmount());
    container.remove();
    if (scroll) Object.defineProperty(HTMLElement.prototype, 'scrollTo', scroll);
    else delete HTMLElement.prototype.scrollTo;
    vi.unstubAllGlobals();
};

const setInput = async (container, selector, value) => {
    const input = container.querySelector(selector);
    await act(async () => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
    });
};

const clickButton = async (container, text) => {
    const button = [...container.querySelectorAll('button')].find(b => b.textContent.trim() === text);
    await act(async () => button.click());
    return button;
};

beforeEach(() => {
    localStorage.clear();
    capture.previewArgs = null;
    capture.executeBody = null;
});

it('previews the role arrangement for the selected role workflow and flags stale inputs', async () => {
    const { container, root, scroll } = await render();
    try {
        await setInput(container, 'input[placeholder="execution.intent_placeholder"]', 'Analyze');
        await clickButton(container, 'execution.match');

        // Two candidates -> selection dialog; pick the role variant.
        const roleCandidate = [...container.querySelectorAll('button')]
            .find(button => button.textContent.includes('orchestration.roleMode'));
        await act(async () => roleCandidate.click());

        const panel = container.querySelector('[data-testid="role-preview-panel"]');
        expect(panel).not.toBeNull();

        const scopeIncomplete = '请完整填写租户/地点/业务对象，或全部留空使用服务器默认范围';
        await setInput(container, '[data-scope-field="tenant"]', 't');
        await act(async () => container.querySelector('[data-testid="role-preview-button"]').click());
        expect(container.textContent).toContain('execution.scope_incomplete');
        expect(capture.previewArgs).toBeNull();

        await setInput(container, '[data-scope-field="tenant"]', '');
        await act(async () => container.querySelector('[data-testid="role-preview-button"]').click());
        expect(capture.previewArgs).toEqual({ psop_id: 'wf-role' });
        expect(container.textContent).toContain('inst-a');
        expect(container.textContent).toContain('inst-b');
        expect(container.textContent).toContain('OUT_OF_SCOPE');
        expect(container.textContent).toContain('execution.preview_can_execute');
        expect(container.textContent).not.toContain('127.0.0.1');

        // Edited scope input invalidates the previous arrangement.
        await setInput(container, '[data-scope-field="site"]', 'city-a');
        expect(container.textContent).toContain('execution.preview_stale');

        // Selecting the instance workflow removes the role preview panel.
        const instanceCard = [...container.querySelectorAll('div.cursor-pointer')]
            .find(card => card.textContent.includes('Instance flow'));
        await act(async () => instanceCard.click());
        expect(container.querySelector('[data-testid="role-preview-panel"]')).toBeNull();
    } finally {
        await teardown(root, container, scroll);
    }
});

it('sends the joined scope once all three parts are filled', async () => {
    const { container, root, scroll } = await render();
    try {
        await setInput(container, 'input[placeholder="execution.intent_placeholder"]', 'Analyze');
        await clickButton(container, 'execution.match');
        const roleCandidate = [...container.querySelectorAll('button')]
            .find(button => button.textContent.includes('orchestration.roleMode'));
        await act(async () => roleCandidate.click());

        await setInput(container, '[data-scope-field="tenant"]', 't');
        await setInput(container, '[data-scope-field="site"]', 'city-a');
        await setInput(container, '[data-scope-field="business_object"]', 'b');
        await act(async () => container.querySelector('[data-testid="role-preview-button"]').click());
        expect(capture.previewArgs).toEqual({ psop_id: 'wf-role', scope: 't/city-a/b' });
        expect(container.textContent).toContain('t/city-a/b');
    } finally {
        await teardown(root, container, scroll);
    }
});

const selectRoleWorkflow = async (container) => {
    await setInput(container, 'input[placeholder="execution.intent_placeholder"]', 'Analyze');
    await clickButton(container, 'execution.match');
    const roleCandidate = [...container.querySelectorAll('button')]
        .find(button => button.textContent.includes('orchestration.roleMode'));
    await act(async () => roleCandidate.click());
    await act(async () => container.querySelector('[data-testid="role-preview-button"]').click());
};

it('re-previews with an override and confirms execution with the digest', async () => {
    const { container, root, scroll } = await render();
    try {
        await selectRoleWorkflow(container);

        const confirmButton = container.querySelector('[data-testid="role-execute-button"]');
        expect(confirmButton).not.toBeNull();
        expect(confirmButton.disabled).toBe(false);

        // Candidate click overrides the task and re-previews with the override.
        const candidate = container.querySelector('[data-testid="role-preview-candidate"]');
        await act(async () => candidate.click());
        expect(capture.previewArgs).toEqual({
            psop_id: 'wf-role', task_overrides: { t1: 'inst-a' }, group_overrides: {},
        });
        expect(container.textContent).toContain('execution.preview_reason_override');

        // The override can be reset back to automatic selection.
        await act(async () => container.querySelector('[data-testid="role-preview-reset"]').click());
        expect(capture.previewArgs).toEqual({ psop_id: 'wf-role' });

        // Re-apply the override and confirm the arrangement.
        await act(async () => candidate.click());
        await act(async () => container.querySelector('[data-testid="role-execute-button"]').click());
        expect(capture.executeBody).toEqual({
            psop_id: 'wf-role',
            task_overrides: { t1: 'inst-a' },
            group_overrides: {},
            confirm_fingerprint: 'b'.repeat(64),
            user_intent: 'Analyze',
            lang: 'en',
        });
    } finally {
        await teardown(root, container, scroll);
    }
});

it('blocks confirmation while the inputs are stale', async () => {
    const { container, root, scroll } = await render();
    try {
        await selectRoleWorkflow(container);
        const confirmButton = container.querySelector('[data-testid="role-execute-button"]');
        expect(confirmButton.disabled).toBe(false);

        await setInput(container, '[data-scope-field="site"]', 'city-a');
        expect(confirmButton.disabled).toBe(true);
        expect(capture.executeBody).toBeNull();
    } finally {
        await teardown(root, container, scroll);
    }
});
