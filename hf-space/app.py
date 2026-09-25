#!/usr/bin/env python3
"""Entry point for the Hugging Face Space.

The page itself is serve.build_ui(), exactly the one you get locally -- this
only changes how it is launched: bound to every interface on the port Spaces
expects, no browser to open, and a short queue because the free tier is a
shared CPU and a long queue only turns one slow job into ten.
"""

import serve

if __name__ == "__main__":
    serve.build_ui().queue(max_size=4).launch(
        server_name="0.0.0.0", server_port=7860, show_api=False)
