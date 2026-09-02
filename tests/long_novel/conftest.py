def pytest_configure(config) -> None:  # type: ignore[no-untyped-def]
    config.addinivalue_line(
        "markers",
        "long_novel: isolated Plan 52 synthetic long-novel scale evidence",
    )
