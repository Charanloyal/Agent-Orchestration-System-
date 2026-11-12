import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { StyleReport, StyleRewrite } from "../api/types";
import { mockFetch, renderRoutes } from "../test/utils";
import { StylePage } from "./StylePage";

const WS = "w1";

function report(overrides: Partial<StyleReport>): StyleReport {
  return {
    words: 40, sentences: 2, paragraphs: 1, mean_sentence_words: 20, sentence_length_cv: 0.1,
    shortest_sentence: 18, longest_sentence: 22, vocabulary_mattr: 0.8, word_entropy_bits: 5,
    stock_phrases: 2, stock_phrases_per_1000_words: 50, paragraph_length_cv: 0, flagged: [0],
    sentence_list: [
      { text: "Moreover, we delve into 2024 results.", words: 6, phrases: ["moreover,", "delve into"] },
      { text: "Revenue rose 12% [1].", words: 4, phrases: [] },
    ],
    ...overrides,
  };
}

const RESULT: StyleRewrite = {
  source: "pasted text",
  persona: "journalist",
  original: "Moreover, we delve into 2024 results. Revenue rose 12% [1].",
  rewritten: "We examine 2024 results. Revenue rose 12% [1].",
  before: report({}),
  after: report({
    sentence_length_cv: 0.35, stock_phrases: 0, stock_phrases_per_1000_words: 0, flagged: [],
    sentence_list: [
      { text: "We examine 2024 results.", words: 4, phrases: [] },
      { text: "Revenue rose 12% [1].", words: 4, phrases: [] },
    ],
  }),
  fact_lock: { total: 3, preserved: 3, missing: [] },
  passes: 1,
  changed_sentences: 1,
  rejected_changes: 0,
};

function render(path = `/w/${WS}/style`) {
  const calls = mockFetch([
    { path: `/api/v1/workspaces/${WS}/uploads`, body: [] },
    { method: "POST", path: `/api/v1/workspaces/${WS}/style/rewrite`, body: RESULT },
  ]);
  renderRoutes([{ path: "w/:workspaceId/style", element: <StylePage /> }], path);
  return calls;
}

describe("StylePage", () => {
  it("rewrites pasted text and shows measured before and after values with the fact lock", async () => {
    const user = userEvent.setup();
    const calls = render();
    const submit = await screen.findByRole("button", { name: "Measure and rewrite" });
    expect(submit).toBeDisabled();
    await user.click(screen.getByLabelText("Text to measure and rewrite"));
    await user.paste(RESULT.original);
    await user.selectOptions(screen.getByLabelText("Voice"), "academic");
    await user.click(submit);

    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ text: RESULT.original, persona: "academic" });
    const metrics = await screen.findByRole("region", { name: "Measurements before and after" });
    expect(within(metrics).getByRole("heading", { name: "Sentence-length variation" })).toBeInTheDocument();
    expect(within(metrics).getByText(/0\.10/)).toHaveTextContent("0.10 → to 0.35");
    expect(screen.getByTestId("fact-lock")).toHaveTextContent("3 / 3");
    expect(screen.getByText("Moreover, we delve into 2024 results.").closest("mark")).not.toBeNull();
    expect(screen.getByText(/not a prediction of who or what wrote it/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download .md" })).toBeInTheDocument();
  });

  it("opens with a workspace document preselected from the Documents page", async () => {
    const user = userEvent.setup();
    const calls = render(`/w/${WS}/style?upload=u1`);
    await user.click(await screen.findByRole("button", { name: "Measure and rewrite" }));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ upload_id: "u1", persona: "journalist" });
  });
});
