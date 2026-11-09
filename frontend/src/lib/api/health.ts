import { apiRequest, invalidResponse, isRecord } from './client.js';
import type { paths } from './generated/schema.js';

type Health = paths['/health']['get']['responses'][200]['content']['application/json'];

export async function getHealth(signal?: AbortSignal): Promise<Health> {
	const data = await apiRequest<unknown>('/health', { signal, cache: 'no-store' }, 3000);
	if (!isRecord(data) || data.status !== 'ok') throw invalidResponse();
	return { status: data.status };
}
