// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0

import { memo } from 'react';
import { AlertTriangle, CheckCircle2, Eye, Loader2, RefreshCw, Users, XCircle } from 'lucide-react';

const SELECTION_REASON_KEYS = {
    highest_priority: 'execution.preview_reason_highest_priority',
    instance_id_tie_break: 'execution.preview_reason_tie_break',
    explicit_override: 'execution.preview_reason_override',
};

const SCOPE_FIELDS = [
    { key: 'tenant', labelKey: 'execution.scope_tenant' },
    { key: 'site', labelKey: 'execution.scope_site' },
    { key: 'business_object', labelKey: 'execution.scope_business_object' },
];

const ReasonBadge = ({ reason, t }) => (
    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
        {t(SELECTION_REASON_KEYS[reason] || reason)}
    </span>
);

const PreviewUnitCard = memo(({ unit, t }) => (
    <div className="p-3 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/50" data-testid="role-preview-unit">
        <div className="flex items-center gap-2 flex-wrap mb-2">
            <span className="text-xs font-semibold text-zinc-900 dark:text-white">
                {unit.task_ids.join(', ')}
            </span>
            {unit.binding_group && (
                <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-violet-100 dark:bg-violet-900/30 text-violet-600 dark:text-violet-400">
                    {unit.binding_group}
                </span>
            )}
        </div>
        <div className="text-[11px] text-zinc-500 dark:text-zinc-400 mb-2">
            {unit.required_skills.map(skill => (
                <div key={skill.task_id}>
                    {`${skill.role_id}@${skill.role_version || '-'} · ${skill.skill_id}`}
                </div>
            ))}
        </div>
        <div className="space-y-1.5 text-[11px]">
            <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-zinc-400 dark:text-zinc-500">{t('execution.preview_current')}</span>
                {unit.current_selection ? (
                    <>
                        <span className="font-semibold text-zinc-700 dark:text-zinc-200">
                            {unit.current_selection.instance_id}
                        </span>
                        {unit.current_selection.agent_name && (
                            <span className="text-zinc-500 dark:text-zinc-400">
                                ({unit.current_selection.agent_name})
                            </span>
                        )}
                        <ReasonBadge reason={unit.current_selection.selection_reason} t={t} />
                    </>
                ) : (
                    <span className="text-rose-500 dark:text-rose-400">{t('execution.preview_no_selection')}</span>
                )}
            </div>
            <div className="flex items-start gap-1.5 flex-wrap">
                <span className="text-zinc-400 dark:text-zinc-500 shrink-0 mt-0.5">{t('execution.preview_candidates')}</span>
                {unit.candidates.length === 0 ? (
                    <span className="text-zinc-400 dark:text-zinc-500">{t('execution.preview_no_candidates')}</span>
                ) : (
                    unit.candidates.map(candidate => (
                        <span key={candidate.instance_id}
                            data-instance-id={candidate.instance_id}
                            className={`px-1.5 py-0.5 rounded border text-[10px] font-medium
                                ${unit.current_selection?.instance_id === candidate.instance_id
                                    ? 'border-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400'
                                    : 'border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300'}`}>
                            {`${candidate.instance_id} · ${candidate.priority}`}
                        </span>
                    ))
                )}
            </div>
            {unit.exclusions.length > 0 && (
                <div className="flex items-start gap-1.5 flex-wrap">
                    <span className="text-zinc-400 dark:text-zinc-500 shrink-0 mt-0.5">{t('execution.preview_excluded')}</span>
                    {unit.exclusions.map((exclusion, index) => (
                        <span key={exclusion.instance_id || `hidden-${index}`}
                            data-instance-id={exclusion.instance_id || 'aggregate'}
                            className="px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 text-[10px]">
                            {`${exclusion.instance_id || '?'}: ${exclusion.reasons.join(', ')}`}
                        </span>
                    ))}
                </div>
            )}
        </div>
    </div>
));

const RolePreviewPanel = memo(({ theme, t, preview, stale, loading, error, scope, onScopeChange, onPreview }) => (
    <div className="mt-4 pt-4 border-t border-zinc-200 dark:border-zinc-700" data-testid="role-preview-panel">
        <div className="flex items-center gap-2 mb-3">
            <Users size={14} className="text-zinc-500" />
            <span className="text-xs font-bold text-zinc-500 dark:text-zinc-400 uppercase">
                {t('execution.preview_title')}
            </span>
            {preview && stale && (
                <span role="status" className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400">
                    {t('execution.preview_stale')}
                </span>
            )}
        </div>
        <div className="flex items-end gap-3 flex-wrap">
            {SCOPE_FIELDS.map(field => (
                <div key={field.key} className="min-w-[140px]">
                    <label className="block text-[10px] font-bold text-zinc-500 dark:text-zinc-400 mb-1 uppercase">
                        {t(field.labelKey)}
                    </label>
                    <input
                        type="text"
                        value={scope[field.key] || ''}
                        onChange={(e) => onScopeChange(field.key, e.target.value)}
                        placeholder={field.key}
                        data-scope-field={field.key}
                        className={`w-full h-9 px-3 rounded-lg border text-xs font-medium outline-none transition-all focus:border-blue-500 ${theme.input}`}
                    />
                </div>
            ))}
            <button
                onClick={onPreview}
                disabled={loading}
                data-testid="role-preview-button"
                className="flex items-center gap-2 px-4 h-9 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-medium transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
            >
                {loading ? <Loader2 size={13} className="animate-spin" /> : <Eye size={13} />}
                {loading ? t('execution.previewing') : (preview ? t('execution.preview_again') : t('execution.preview'))}
            </button>
        </div>

        {error && (
            <div role="alert" className="mt-3 flex items-center gap-2 text-xs text-rose-600 dark:text-rose-400">
                <XCircle size={13} />
                {error}
            </div>
        )}

        {preview && (
            <div className="mt-3 space-y-2">
                <div className="flex items-center gap-2 flex-wrap text-[11px]">
                    {preview.can_execute ? (
                        <span role="status" className="flex items-center gap-1 font-medium text-emerald-600 dark:text-emerald-400">
                            <CheckCircle2 size={13} />
                            {t('execution.preview_can_execute')}
                        </span>
                    ) : (
                        <span role="alert" className="flex items-center gap-1 font-medium text-rose-600 dark:text-rose-400">
                            <XCircle size={13} />
                            {t('execution.preview_blocked')}
                        </span>
                    )}
                    {preview.execution_scope && (
                        <span className="text-zinc-400 dark:text-zinc-500">
                            {`${t('execution.scope')}: ${preview.execution_scope}`}
                        </span>
                    )}
                    {preview.catalog_version && (
                        <span className="text-zinc-400 dark:text-zinc-500">
                            {`${t('execution.preview_catalog')}: ${preview.catalog_version}`}
                        </span>
                    )}
                </div>

                {preview.issues.length > 0 && (
                    <div className="space-y-1" data-testid="role-preview-issues">
                        {preview.issues.map((issue, index) => (
                            <div key={`${issue.code}-${index}`}
                                role="alert"
                                className="flex items-start gap-2 p-2 rounded-lg bg-rose-50 dark:bg-rose-900/20 text-[11px] text-rose-600 dark:text-rose-400">
                                <AlertTriangle size={12} className="shrink-0 mt-0.5" />
                                <div>
                                    <span className="font-bold">{issue.code}</span>
                                    {issue.task_ids?.length > 0 && (
                                        <span className="ml-1 opacity-80">({issue.task_ids.join(', ')})</span>
                                    )}
                                    <div className="opacity-90">{issue.message}</div>
                                </div>
                            </div>
                        ))}
                    </div>
                )}

                <div className="space-y-2">
                    {preview.units.map(unit => (
                        <PreviewUnitCard key={unit.unit_id} unit={unit} t={t} />
                    ))}
                </div>

                {stale && (
                    <div className="flex items-center gap-1.5 text-[11px] text-amber-600 dark:text-amber-400">
                        <RefreshCw size={11} />
                        {t('execution.preview_stale_hint')}
                    </div>
                )}
            </div>
        )}
    </div>
));

RolePreviewPanel.displayName = 'RolePreviewPanel';
export default RolePreviewPanel;
