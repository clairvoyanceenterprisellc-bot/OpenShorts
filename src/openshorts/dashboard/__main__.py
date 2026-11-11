import uvicorn


def main(host: str = "127.0.0.1", port: int = 8787) -> None:
    uvicorn.run("openshorts.dashboard.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
