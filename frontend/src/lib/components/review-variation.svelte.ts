import { onDestroy } from 'svelte';
import { SvelteMap, SvelteSet } from 'svelte/reactivity';
import { apiErrorMessage } from '#lib/api/errors.js';
import { getVariationPosition, type VariationPosition } from '#lib/api/review.js';

type Anchor = {
	id: number;
	profile: string | null | undefined;
	ply: number;
	legal: string[];
	recordedMove: string | undefined;
};
type LinePosition = VariationPosition & { error?: string };

export function reviewVariation(anchor: () => Anchor, advanceRecorded: () => void) {
	const maxPlies = 256;
	const positions = new SvelteMap<string, LinePosition>();
	const roots = new SvelteMap<string, LinePosition>();
	const rootErrors = new SvelteMap<string, string>();
	const pendingRoots = new SvelteSet<string>();
	const lifetime = new AbortController();
	let session = new AbortController();
	onDestroy(() => {
		lifetime.abort();
		session.abort();
	});

	let line = $state<string[]>([]);
	let cursor = $state(0);
	let from = $state('');
	let promotions = $state<string[]>([]);
	let moving = $state(false);
	let moveError = $state('');
	let searches = Promise.resolve();

	const prefix = $derived(line.slice(0, cursor));
	const nodes = $derived(line.map((_, index) => positions.get(line.slice(0, index + 1).join(' '))));
	const current = $derived(nodes[cursor - 1]);
	const legal = $derived(
		cursor === 0 ? anchor().legal : cursor < maxPlies ? (current?.legal_moves ?? []) : []
	);
	const sources = $derived(legal.map((move) => move.slice(0, 2)));
	const destinations = $derived(
		from ? legal.filter((move) => move.startsWith(from)).map((move) => move.slice(2, 4)) : []
	);
	const rootKey = $derived.by(() => {
		const { id, profile, ply } = anchor();
		return `${id}:${profile}:${ply}`;
	});

	$effect(() => {
		const at = anchor();
		const key = rootKey;
		if (cursor !== 0 || !at.profile || !at.legal.length) return;
		// Skip brief stops while scrubbing the recorded game.
		const timer = setTimeout(() => loadRoot(at, key), 120);
		return () => clearTimeout(timer);
	});

	function request(at: Anchor, moves: string[], evaluate: boolean, signal: AbortSignal) {
		if (!at.profile) throw new Error('The recorded analysis profile is unavailable.');
		return getVariationPosition(
			at.id,
			{ profile_hash: at.profile, ply: at.ply, line: moves, evaluate },
			signal
		);
	}

	function loadRoot(at: Anchor, key: string) {
		if (pendingRoots.has(key) || roots.get(key)?.evaluation) return;
		pendingRoots.add(key);
		rootErrors.delete(key);
		searches = searches.then(async () => {
			try {
				if (!lifetime.signal.aborted && rootKey === key && cursor === 0) {
					const result = await request(at, [], true, lifetime.signal);
					if (!lifetime.signal.aborted) roots.set(key, result);
				}
			} catch (error) {
				if (!lifetime.signal.aborted) {
					rootErrors.set(key, apiErrorMessage(error, 'Could not load engine lines.'));
				}
			} finally {
				pendingRoots.delete(key);
			}
		});
	}

	function evaluate(moves: string[]) {
		const key = moves.join(' ');
		const node = positions.get(key);
		if (!node || node.evaluation) return;
		const { signal } = session;
		const at = anchor();
		positions.set(key, { ...node, error: undefined });
		// Serialize evaluations even when the user jumps to a different recorded position.
		searches = searches.then(async () => {
			if (signal.aborted) return;
			try {
				const result = await request(at, moves, true, lifetime.signal);
				if (!signal.aborted) positions.set(key, result);
			} catch (error) {
				if (!signal.aborted) {
					positions.set(key, {
						...node,
						error: apiErrorMessage(error, 'Could not evaluate this position.')
					});
				}
			}
		});
	}

	async function play(uci: string) {
		if (moving || !legal.includes(uci)) return;
		const at = anchor();
		if (cursor === 0 && uci === at.recordedMove) {
			advanceRecorded();
			return;
		}
		const next = [...prefix, uci];
		const key = next.join(' ');
		const { signal } = session;
		moving = true;
		moveError = '';
		try {
			const existing = positions.get(key);
			const result = existing ?? (await request(at, next, false, signal));
			if (signal.aborted) return;
			positions.set(key, result);
			if (line[cursor] !== uci) line = next;
			setCursor(next.length);
			if (!existing) evaluate(next);
		} catch (error) {
			if (!signal.aborted)
				moveError = apiErrorMessage(error, 'Could not play this move. Try it again.');
		} finally {
			if (!signal.aborted) moving = false;
		}
	}

	function setCursor(index: number) {
		cursor = index;
		from = '';
		promotions = [];
		moveError = '';
	}

	function chooseMove(start: string, end: string) {
		const options = legal.filter((move) => move.startsWith(start + end));
		if (options.length > 1) promotions = options;
		else if (options.length === 1) void play(options[0]);
	}

	return {
		get active() {
			return line.length > 0;
		},
		get cursor() {
			return cursor;
		},
		get nodes() {
			return nodes;
		},
		get current() {
			return current;
		},
		get rootEvaluation() {
			return roots.get(rootKey)?.evaluation;
		},
		get rootError() {
			return rootErrors.get(rootKey);
		},
		get atLimit() {
			return cursor === maxPlies;
		},
		get lastMove() {
			return line[cursor - 1];
		},
		get from() {
			return from;
		},
		get promotions() {
			return promotions;
		},
		get moving() {
			return moving;
		},
		get moveError() {
			return moveError;
		},
		get legal() {
			return legal;
		},
		get sources() {
			return sources;
		},
		get destinations() {
			return destinations;
		},
		play,
		chooseMove,
		selectSquare(square: string) {
			if (from && destinations.includes(square)) chooseMove(from, square);
			else from = from !== square && sources.includes(square) ? square : '';
		},
		dragSource(square: string) {
			from = square;
		},
		cancelPromotion() {
			promotions = [];
		},
		jump(index: number) {
			if (!moving && index >= 0 && index <= line.length) setCursor(index);
		},
		retryEvaluation() {
			if (cursor === 0) loadRoot(anchor(), rootKey);
			else evaluate(prefix);
		},
		reset() {
			session.abort();
			session = new AbortController();
			positions.clear();
			line = [];
			moving = false;
			setCursor(0);
		}
	};
}
