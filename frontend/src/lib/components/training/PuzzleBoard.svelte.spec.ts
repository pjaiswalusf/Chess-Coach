import { page, userEvent } from 'vitest/browser';
import { expect, it, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import PuzzleBoard from './PuzzleBoard.svelte';
import type { PublicPuzzle } from '#lib/api/training.js';

const puzzle: PublicPuzzle = {
	solver_moves: 1,
	id: 1,
	fen: 'rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2',
	side_to_move: 'white',
	theme: 'critical_capture',
	difficulty: 'medium',
	attempt_count: 0,
	legal_moves: ['e4d5']
};

it('selects a White capture with the keyboard and exposes the selection', async () => {
	const onMove = vi.fn();
	render(PuzzleBoard, { puzzle, onMove });
	const from = page.getByRole('button', { name: 'e4: White pawn' });
	await from.click();
	await expect.element(from).toHaveAttribute('aria-pressed', 'true');
	const destination = page.getByRole('button', { name: /d5: Black pawn/ }).element();
	(destination as HTMLButtonElement).focus();
	await userEvent.keyboard('{Enter}');
	expect(onMove).toHaveBeenLastCalledWith('e4d5');
});

it('orients for Black and selects a castling move supplied by the API', async () => {
	const onMove = vi.fn();
	render(PuzzleBoard, {
		puzzle: {
			...puzzle,
			fen: 'r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1',
			side_to_move: 'black',
			legal_moves: ['e8g8']
		},
		onMove
	});
	const board = page.getByRole('group', { name: /Black at bottom/ });
	await expect.element(board.getByRole('button').first()).toHaveAttribute('data-square', 'h1');
	await board.getByRole('button', { name: 'e8: Black king' }).click();
	await board.getByRole('button', { name: /g8: empty/ }).click();
	expect(onMove).toHaveBeenLastCalledWith('e8g8');
});

it('requires an explicit promotion choice and locks controls during submission', async () => {
	const onMove = vi.fn();
	const promotion = {
		...puzzle,
		fen: '7k/P7/8/8/8/8/8/7K w - - 0 1',
		legal_moves: ['a7a8q', 'a7a8r', 'a7a8b', 'a7a8n']
	};
	const view = render(PuzzleBoard, { puzzle: promotion, onMove });
	await page.getByRole('button', { name: 'a7: White pawn' }).click();
	await page.getByRole('button', { name: /a8: empty/ }).click();
	expect(onMove).toHaveBeenLastCalledWith(null);
	await page.getByLabelText('Promote to').selectOptions('a7a8n');
	expect(onMove).toHaveBeenLastCalledWith('a7a8n');
	await view.rerender({ puzzle: promotion, onMove, disabled: true });
	await expect.element(page.getByLabelText('Promote to')).toBeDisabled();
	await expect.element(page.getByRole('button', { name: 'a7: White pawn' })).toBeDisabled();
});
