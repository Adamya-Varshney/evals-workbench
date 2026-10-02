import { expect, test } from "@playwright/test";

/** Completes a review session using only the keyboard. */
test("review a batch with the keyboard only", async ({ page, request }) => {
  const p = await (await request.post("/api/projects/demo")).json();
  const job = await (await request.post(`/api/projects/${p.id}/imports`, { multipart: { demo: "true" } })).json();
  await request.post(`/api/projects/${p.id}/imports/${job.id}/commit`, { data: { mapping: job.mapping, redaction: {} } });
  await request.patch(`/api/projects/${p.id}`, { data: { reviewer_name: "E2E" } });
  const batch = await (await request.post(`/api/projects/${p.id}/batches`, { data: { size: 8, seed: 11 } })).json();

  await page.goto(`/p/${p.id}/review?batch=${batch.id}`);
  const progress = page.getByTestId("progress");
  await expect(progress).toContainText("0 of 8 reviewed");
  await expect(page.getByTestId("meta-strip")).toBeVisible();

  // From here on: keyboard only.
  await page.keyboard.press("?");
  await expect(page.getByTestId("shortcuts")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("shortcuts")).toBeHidden();

  const notes = ["Markdown bullets in an SMS", "Said it would check and never did", "Called an in-person tour virtual"];
  for (let i = 0; i < 8; i++) {
    const firstId = await page.locator("[data-event-id]").first().getAttribute("data-event-id");
    if (i % 3 === 0) {
      await page.keyboard.press("f"); // fail focuses the note
      await expect(page.getByTestId("note")).toBeFocused();
      await page.keyboard.type(notes[i % notes.length]);
      await page.keyboard.press("Escape");
      await expect(page.getByTestId("note")).not.toBeFocused();
      await page.keyboard.press("]");
      await page.keyboard.press("a"); // mark the first failure on the first turn
      await expect(page.getByText("first failure").first()).toBeVisible();
      await page.keyboard.press("n");
      await page.keyboard.type(" (first reply)");
      await page.keyboard.press("Control+Enter"); // save & next from inside the note
    } else if (i === 4) {
      await page.keyboard.press("d"); // come back later
      await expect(page.getByTestId("defer-btn")).toContainText("Marked");
      await page.keyboard.press("j");
    } else {
      await page.keyboard.press("p");
      await expect(page.getByTestId("pass-btn")).toHaveAttribute("aria-pressed", "true");
      await page.keyboard.press("Control+Enter");
    }
    if (i < 7) await expect(page.locator("[data-event-id]").first()).not.toHaveAttribute("data-event-id", firstId!);
  }
  await expect(progress).toContainText("7 of 8 reviewed");

  // Go back to the deferred trace and pass it; then undo and redo.
  await page.keyboard.press("k");
  await page.keyboard.press("k");
  await page.keyboard.press("k");
  await expect(page.getByTestId("defer-btn")).toContainText("Marked");
  await page.keyboard.press("p");
  await expect(progress).toContainText("8 of 8 reviewed");
  await page.keyboard.press("z");
  await expect(page.getByTestId("pass-btn")).toHaveAttribute("aria-pressed", "false");
  await expect(progress).toContainText("7 of 8 reviewed");
  await page.keyboard.press("p");
  await expect(progress).toContainText("8 of 8 reviewed");

  // Toggles
  await page.keyboard.press("s");
  await expect(page.getByText("You are Lark").first()).toBeVisible();
  await page.keyboard.press("r");
  await expect(page.locator("pre").filter({ hasText: '"messages"' }).first()).toBeVisible();
  await page.keyboard.press("r");

  // Everything saved server-side, with the note and anchor.
  const reviews = await Promise.all(
    (await (await request.get(`/api/projects/${p.id}/review/queue?batch_id=${batch.id}`)).json()).map((q: any) =>
      request.get(`/api/projects/${p.id}/review/trace/${q.id}`).then((r) => r.json()),
    ),
  );
  const fails = reviews.filter((r: any) => r.review?.verdict === "fail");
  expect(fails.length).toBe(3);
  for (const f of fails) {
    expect(f.review.note).toContain("(first reply)");
    expect(f.review.first_failure_event_id).not.toBeNull();
    expect(f.review.reviewer).toBe("E2E");
  }
});
