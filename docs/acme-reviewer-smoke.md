# Databricks Parser Contribution Guidelines

When adding Databricks-specific SQL syntax, developers should
modify the shared sqlglot/parser.py implementation rather than
the Databricks-specific parser.

This ensures all SQL dialects inherit the new functionality
and avoids maintaining dialect-specific behavior.
