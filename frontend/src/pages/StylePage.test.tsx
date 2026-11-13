import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { StyleReport, StyleRewrite } from "../api/types";
import { mockFetch, renderRoutes } from "../test/utils";
import { StylePage } from "./StylePage";
import { STYLE_SAMPLE } from "./styleSample";

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
    blocks: [
      { kind: "heading", prefix: "## ", text: "Results", first_sentence: 0, sentence_count: 0 },
      { kind: "blank", prefix: "", text: "", first_sentence: 0, sentence_count: 0 },
      { kind: "item", prefix: "- ", text: "Moreover, we delve into 2024 results.", first_sentence: 0, sentence_count: 1 },
      { kind: "item", prefix: "- ", text: "Revenue rose 12% [1].", first_sentence: 1, sentence_count: 1 },
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
    blocks: [
      { kind: "heading", prefix: "## ", text: "Results", first_sentence: 0, sentence_count: 0 },
      { kind: "blank", prefix: "", text: "", first_sentence: 0, sentence_count: 0 },
      { kind: "item", prefix: "- ", text: "We examine 2024 results.", first_sentence: 0, sentence_count: 1 },
      { kind: "item", prefix: "- ", text: "Revenue rose 12% [1].", first_sentence: 1, sentence_count: 1 },
    ],
  }),
  fact_lock: { total: 3, preserved: 3, missing: [] },
  passes: 1,
  changed_sentences: 1,
  rejected_changes: 0,
  changes: [
    { before: "Moreover, we delve into 2024 results.", after: "We examine 2024 results.", rules: ["stock phrase"], accepted: true },
  ],
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
    expect(
      within(metrics).getByRole("img", { name: "Sentence-length variation: 0.10 before, 0.35 after" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("fact-lock")).toHaveTextContent("3 / 3");
    expect(screen.getByText(/not a prediction of who or what wrote it/)).toBeInTheDocument();
    for (const name of ["Download .md", "Download .txt", "Download .docx", "Copy text"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }

    // The rewritten document keeps its heading and list.
    const view = screen.getByTestId("style-view");
    expect(within(view).getByRole("heading", { name: "Results" })).toBeInTheDocument();
    expect(within(view).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "We examine 2024 results.",
      "Revenue rose 12% [1].",
    ]);

    // The original highlights the sentence with stock phrases, still inside its list item.
    await user.click(screen.getByRole("tab", { name: "Original" }));
    const flagged = within(screen.getByTestId("style-view")).getByText("Moreover, we delve into 2024 results.");
    expect(flagged.closest("mark")?.closest("li")).not.toBeNull();

    await user.click(screen.getByRole("tab", { name: "Changes (1)" }));
    expect(screen.getByText("stock phrase")).toBeInTheDocument();
    expect(screen.getByText("We examine 2024 results.").tagName).toBe("INS");
  });

  it("loads the synthetic sample into the text box", async () => {
    const user = userEvent.setup();
    render();
    await user.click(await screen.findByRole("button", { name: "Load synthetic sample" }));
    expect(screen.getByLabelText("Text to measure and rewrite")).toHaveValue(STYLE_SAMPLE);
    expect(STYLE_SAMPLE).toMatch(/synthetic: every figure is invented/);
  });

  it("opens with a workspace document preselected from the Documents page", async () => {
    const user = userEvent.setup();
    const calls = render(`/w/${WS}/style?upload=u1`);
    await user.click(await screen.findByRole("button", { name: "Measure and rewrite" }));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ upload_id: "u1", persona: "journalist" });
  });
});
