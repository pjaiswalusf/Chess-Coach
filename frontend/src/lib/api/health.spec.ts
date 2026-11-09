import { afterEach, expect, test, vi } from 'vitest';
import { getHealth } from './health.js';

afterEach(() => vi.unstubAllGlobals());

test.each([null, {}, { status: 'down' }, [{ status: 'ok' }]])(
	'rejects a successful response with an invalid health payload (%j)',
	async (payload) => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(payload)));
		await expect(getHealth()).rejects.toMatchObject({ kind: 'invalid_response' });
	}
);
