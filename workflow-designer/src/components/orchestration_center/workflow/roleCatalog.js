// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from 'react';
import { getRoleCatalog } from '@/service/api.js';

/** A display projection is usable only for the requested release. No latest fallback. */
export const useRoleCatalog = (version, enabled) => {
    const [result, setResult] = useState(null);
    useEffect(() => {
        if (!enabled || !version) return;
        let cancelled = false;
        getRoleCatalog(version).then(catalog => {
            if (!cancelled) setResult({ version, catalog: catalog?.catalog_version === version ? catalog : null });
        }).catch(() => {
            if (!cancelled) setResult({ version, catalog: null });
        });
        return () => { cancelled = true; };
    }, [version, enabled]);
    const current = result?.version === version ? result : null;
    return { catalog: enabled ? current?.catalog || null : null,
        unavailable: enabled && (!version || (current !== null && !current.catalog)) };
};

export const decorateRoleNodes = (nodes, catalog) => nodes.map(node => ({ ...node, data: {
    ...node.data,
    ...(node.data?.subtasks ? { subtasks: node.data.subtasks.map(task => {
        const { roleName: _roleName, skillName: _skillName, ...identity } = task;
        if (task.binding !== 'role') return identity;
        const role = catalog?.roles?.find(role => role.role_id === task.agent && role.role_version === task.role_version);
        const skill = role?.skills?.find(skill => skill.skill_id === task.skill);
        return skill ? { ...identity, roleName: role.name, skillName: skill.name } : identity;
    }) } : {}),
} }));
