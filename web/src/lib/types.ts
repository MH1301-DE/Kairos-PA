export type Confidence = 'high' | 'medium' | 'low' | 'insufficient_data';

export interface MetricResult {
	metric_id: string;
	variant: string;
	value: number | Record<string, number> | null;
	unit: string;
	confidence: Confidence;
	coverage_days: number;
	coverage_required_days: number;
	as_of: string;
}

export interface ConnectionInfo {
	connector: string;
	status: string;
	external_account: string | null;
	connected_at: string;
	last_ok_at: string | null;
	token_refreshed_at: string | null;
	reauth_since: string | null;
}

// mirrors src/kairos/ingestion/job_registry.py SyncJob.to_dict()
export interface SyncJob {
	job_id: string;
	connector: string;
	kind: string;
	from_date: string;
	to_date: string;
	status: string;
	windows_processed: number;
	// null for job kinds with no meaningful window count (e.g. google_calendar's
	// single-fetch "events" sync)
	windows_total: number | null;
	error: string | null;
	started_at: string;
	finished_at: string | null;
}

export interface CalendarEvent {
	id: string;
	summary: string | null;
	description: string | null;
	location: string | null;
	start_at: string;
	end_at: string;
	all_day: boolean;
	status: string;
	source: string;
}

export interface FreeSlot {
	start: string;
	end: string;
}

export interface Goal {
	id: string;
	title: string;
	target_value: number | null;
	target_unit: string | null;
	target_date: string | null;
	notes: string | null;
	status: 'active' | 'completed' | 'abandoned';
	created_at: string;
	updated_at: string;
}

export interface ProfileSettings {
	birth_date: string | null;
	hr_max_override: number | null;
	resting_hr_override: number | null;
	hr_max_used: number | null;
	hr_max_source: 'eingetragen' | 'aus Alter' | null;
	hr_max_measured_12m: number | null;
	hr_max_warning: string | null;
}

export interface MemoryEntry {
	id: string;
	content: string;
	source: 'user' | 'agent';
	created_at: string;
	updated_at: string;
	expires_at: string | null;
}

export interface Conversation {
	id: string;
	title: string | null;
	updated_at: string;
	// set when the conversation belongs to a scheduler job
	scheduled_job_id?: string | null;
}

// tool_calls mirrors ConversationRepository.append_message's tool_calls shape:
// [{id, name, arguments}], arguments is a JSON string
export interface ChatMessage {
	id: string;
	role: 'user' | 'assistant' | 'tool';
	content: string | null;
	tool_calls: { id: string; name: string; arguments: string }[] | null;
	tool_call_id: string | null;
	// null for rows written before the column existed
	tool_name: string | null;
	created_at: string;
	seq?: number;
}

export interface Proposal {
	tool_name: string;
	arguments: Record<string, unknown>;
	summary: string;
	tool_call_id: string;
}

// the tool result shape from src/kairos/agent/tools.py's _envelope()
export interface ToolResult {
	summary: string;
	data: unknown;
	meta: Record<string, unknown>;
}

export interface DashboardTileLayout {
	module_id: string;
	position: number;
	visible: boolean;
}
