export type ApiErrorKind = 'http' | 'network' | 'timeout' | 'invalid_response' | 'cancelled';

export class ApiError extends Error {
	constructor(
		public readonly kind: ApiErrorKind,
		message: string,
		public readonly status?: number,
		public readonly code?: string
	) {
		super(message);
		this.name = 'ApiError';
	}
}

export function apiErrorMessage(error: unknown, fallback: string): string {
	return error instanceof ApiError ? error.message : fallback;
}
