import { defineParams } from '@sveltejs/kit/params';

export const params = defineParams({
	gameId: (value) =>
		/^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)) ? value : undefined
});
