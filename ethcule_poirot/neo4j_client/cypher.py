"""
Neo4j.Cypher — Template Engine for Database Queries

Equivalent of lib/neo4j/chyper.ex in the Elixir project.

Provides a single function that takes a query string with {{placeholders}}
and replaces them with actual values, escaping single quotes to prevent
Cypher injection.

Example:
    >>> prepared_statement(
    ...     "MATCH (n {eth_address: '{{address}}'})",
    ...     {"address": "0xABC"}
    ... )
    "MATCH (n {eth_address: '0xABC'})"
"""


def prepared_statement(query: str, variables: dict[str, str]) -> str:
    """Replace {{placeholder}} tokens in a Cypher query with escaped values.

    Args:
        query: A Cypher query string containing {{key}} placeholders.
        variables: A dict mapping placeholder names to their values.

    Returns:
        The query string with all placeholders replaced and single quotes
        escaped in the substituted values.
    """
    result = query
    for key, value in variables.items():
        # Escape single quotes to prevent Cypher injection
        # (mirrors the Elixir String.replace(value, "'", "\\'"))
        escaped_value = str(value).replace("'", "\\'")
        result = result.replace(f"{{{{{key}}}}}", escaped_value)
    return result
