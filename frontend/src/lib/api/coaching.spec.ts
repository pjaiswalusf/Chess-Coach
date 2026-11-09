import { afterEach, expect, it, vi } from 'vitest';
import { coachingApi } from './coaching';

afterEach(() => vi.unstubAllGlobals());
it('uses only relative backend endpoints with an explicit analysis profile', async () => {
	const fetch = vi.fn().mockImplementation(() => Response.json({ status: 'queued' }));
	vi.stubGlobal('fetch', fetch);
	await coachingApi.generate(1, 3, 'profile');
	expect(fetch).toHaveBeenCalledWith(
		'/api/v1/games/1/moves/3/explanation?profile_hash=profile',
		expect.objectContaining({ method: 'POST' })
	);
	await coachingApi.get(1, 3, 'profile');
	expect(fetch).toHaveBeenLastCalledWith(
		'/api/v1/games/1/moves/3/explanation?profile_hash=profile',
		expect.objectContaining({ method: 'GET' })
	);
});
