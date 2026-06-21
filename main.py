from src.app.fastapi_app import FastApiServer
from src.app.pywebview_app.config import APP_NAME, WINDOW_HEIGHT, WINDOW_MIN_SIZE, WINDOW_WIDTH
from src.app.pywebview_app.webview_api import WebviewApi
from src.app.pywebview_app.webview_server import WebviewStaticServer
from src.config.runtime_config import load_runtime_config


def main() -> None:
    import webview

    api = None
    api_server = None
    static_server = None

    try:
        runtime_config = load_runtime_config()
        api = WebviewApi(
            runtime_config=runtime_config,
            auto_start=runtime_config.app.auto_start_proxy,
        )
        api_server = FastApiServer(api=api)
        api_server.start()
        static_server = WebviewStaticServer(api_base_url=api_server.url)
        static_server.start()
        window = webview.create_window(
            APP_NAME,
            static_server.index_url,
            js_api=api,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            min_size=WINDOW_MIN_SIZE,
        )
        api.set_window(window)
        webview.start()
    finally:
        if static_server is not None:
            static_server.stop()
        if api_server is not None:
            api_server.stop()
        if api is not None:
            api.shutdown()


if __name__ == "__main__":
    main()
