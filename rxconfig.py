import reflex as rx

config = rx.Config(
    app_name="cleaning_shift_mvp",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
    ]
)