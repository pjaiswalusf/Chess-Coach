import type { PageLoad } from './$types';

export const load: PageLoad = ({ params }) => ({ id: Number(params.id) });
