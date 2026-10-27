// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/** Accept either a design PSOP or canvas nodes; never infer roles from names. */
export const hasRoleTasks = (workflowOrNodes) => {
    const steps = Array.isArray(workflowOrNodes) ? workflowOrNodes : workflowOrNodes?.steps || [];
    return steps.some(step => (step.subtasks || step.data?.subtasks || []).some(task => task.binding === 'role'));
};

export const filterNodeChanges = (changes, nodes, protectedWorkflow) => changes.filter(change => {
    if (protectedWorkflow) return ['position', 'dimensions', 'select'].includes(change.type);
    if (change.type !== 'remove') return true;
    const node = nodes.find(item => item.id === change.id);
    return node?.type !== 'startNode' && node?.type !== 'endNode';
});

export const filterEdgeChanges = (changes, protectedWorkflow) => (
    protectedWorkflow ? changes.filter(change => change.type === 'select') : changes
);
