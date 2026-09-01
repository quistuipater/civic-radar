from app.summaries.formatting import highlight_figures


class TestHighlightFigures:
    def test_wraps_standalone_numbers_in_a_figure_span(self):
        result = str(highlight_figures("242 new documents landed."))
        assert '<span class="figure">242</span>' in result

    def test_wraps_multiple_numbers_independently(self):
        result = str(highlight_figures("242 documents, 164 of them campaign finance."))
        assert '<span class="figure">242</span>' in result
        assert '<span class="figure">164</span>' in result

    def test_preserves_comma_separated_numbers_as_one_figure(self):
        result = str(highlight_figures("Budget of 1,234 dollars."))
        assert '<span class="figure">1,234</span>' in result

    def test_escapes_html_in_the_input_before_highlighting(self):
        result = str(highlight_figures("<script>alert(1)</script> 5 items"))
        assert "<script>alert" not in result
        assert '<span class="figure">5</span>' in result

    def test_text_with_no_numbers_is_unchanged_aside_from_escaping(self):
        result = str(highlight_figures("Nothing happened this period."))
        assert result == "Nothing happened this period."
