import { error } from '@sveltejs/kit';
import type { PageLoad } from './$types';

export const load: PageLoad = ({ params }) => {
	const id = Number(params.id);
	if (!/^[1-9]\d*$/.test(params.id) || !Number.isSafeInteger(id)) {
		error(404, 'Game not found.');
	}
	return { id };
};
