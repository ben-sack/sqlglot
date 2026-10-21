from __future__ import annotations

import typing as t

from sqlglot import exp, parser
from sqlglot.dialects.dialect import build_date_delta, build_formatted_time
from sqlglot.helper import seq_get
from sqlglot.parsers.spark import SparkParser
from sqlglot.tokens import TokenType


class DatabricksParser(SparkParser):
    LOG_DEFAULTS_TO_LN = True
    STRICT_CAST = True
    COLON_IS_VARIANT_EXTRACT = True
    COLON_CHAIN_IS_SINGLE_EXTRACT = False

    FUNCTIONS: t.ClassVar[dict[str, t.Callable]] = {
        **SparkParser.FUNCTIONS,
        "IFF": exp.If.from_arg_list,
        "GETDATE": exp.CurrentTimestamp.from_arg_list,
        "DATEDIFF": build_date_delta(exp.DateDiff),
        "DATE_DIFF": build_date_delta(exp.DateDiff),
        "NOW": exp.CurrentTimestamp.from_arg_list,
        "TO_DATE": build_formatted_time(exp.TsOrDsToDate),
        "UNIFORM": lambda args: exp.Uniform(
            this=seq_get(args, 0), expression=seq_get(args, 1), seed=seq_get(args, 2)
        ),
    }

    NO_PAREN_FUNCTION_PARSERS: t.ClassVar = {
        **SparkParser.NO_PAREN_FUNCTION_PARSERS,
        "CURDATE": lambda self: self._parse_curdate(),
    }

    FUNCTION_PARSERS: t.ClassVar[dict[str, t.Callable]] = {
        **SparkParser.FUNCTION_PARSERS,
        "REGR_AVGX": lambda self: self._parse_distinct_arg_function(exp.RegrAvgx, distinct_index=1),
        "REGR_AVGY": lambda self: self._parse_distinct_arg_function(exp.RegrAvgy),
        "REGR_SXX": lambda self: self._parse_distinct_arg_function(exp.RegrSxx, distinct_index=1),
        "REGR_SXY": lambda self: self._parse_distinct_arg_function(exp.RegrSxy),
        "REGR_SYY": lambda self: self._parse_distinct_arg_function(exp.RegrSyy, distinct_index=1),
    }

    FACTOR: t.ClassVar = {
        **SparkParser.FACTOR,
        TokenType.COLON: exp.JSONExtract,
    }

    COLUMN_OPERATORS: t.ClassVar = {
        **parser.Parser.COLUMN_OPERATORS,
        TokenType.QDCOLON: lambda self, this, to: self.build_cast(
            False,
            this=this,
            to=to,
        ),
    }
    CAST_COLUMN_OPERATORS: t.ClassVar = {
        *SparkParser.CAST_COLUMN_OPERATORS,
        TokenType.QDCOLON,
    }

    # Matched by the base describe parser before the table name, same as HISTORY.
    # _match_texts declines the match when DETAIL is the table name instead.
    DESCRIBE_STYLES: t.ClassVar = {
        *SparkParser.DESCRIBE_STYLES,
        "DETAIL",
    }

    def _match_texts(self, texts: parser.TEXTS_TYPE, advance: bool = True) -> bool:
        if texts is self.DESCRIBE_STYLES and self._detail_is_table_name():
            return False
        return super()._match_texts(texts, advance)

    def _detail_is_table_name(self) -> bool:
        # DETAIL names the table in DESCRIBE detail, DESCRIBE TABLE detail,
        # DESCRIBE detail.tbl, and DESCRIBE detail PARTITION (...). It is the
        # style when a table target follows and no creatable kind already did.
        token = self._curr
        if token.token_type in self.TEXT_MATCH_EXCLUDED_TOKENS or token.text.upper() != "DETAIL":
            return False
        if self._prev.token_type in self.CREATABLES:
            return True

        nxt = self._next
        if nxt.token_type in (TokenType.SENTINEL, TokenType.DOT):
            return True
        if (
            nxt.token_type not in self.TEXT_MATCH_EXCLUDED_TOKENS
            and nxt.text.upper() in self.PARTITION_KEYWORDS
            and self._index + 2 < self._tokens_size
            and self._tokens[self._index + 2].token_type == TokenType.L_PAREN
        ):
            return True
        return not (
            nxt.token_type in self.ID_VAR_TOKENS
            or nxt.token_type
            in (TokenType.IDENTIFIER, TokenType.STRING, TokenType.PLACEHOLDER, TokenType.PARAMETER)
        )

    def _parse_curdate(self) -> exp.CurrentDate:
        # CURDATE, an alias for CURRENT_DATE, has optional parentheses
        if self._match(TokenType.L_PAREN):
            self._match_r_paren()
        return self.expression(exp.CurrentDate())

    def _parse_primary_key_part(self) -> exp.Expr | None:
        this = super()._parse_primary_key_part()
        if this and self._match_text_seq("TIMESERIES"):
            return self.expression(exp.TimeseriesKey(this=this))
        return this

    def _parse_cluster_property(self):
        if self._match_texts(("AUTO", "NONE")):
            return self.expression(exp.ClusterProperty(this=self._prev.text.upper()))
        return super()._parse_cluster_property()
