import { useEffect } from "react";

/** Looks like a bare nginx/server error — no app chrome. */
export function Fake500() {
  useEffect(() => {
    const prevTitle = document.title;
    document.title = "500 Internal Server Error";

    const html = document.documentElement;
    const body = document.body;
    const prevHtmlClass = html.className;
    const prevBodyClass = body.className;
    const prevHtmlBg = html.style.background;
    const prevHtmlColor = html.style.color;
    const prevBodyBg = body.style.background;
    const prevBodyColor = body.style.color;

    html.classList.remove("dark");
    body.classList.remove("dark");
    html.style.background = "#f0f0f0";
    html.style.color = "#222";
    body.style.background = "#f0f0f0";
    body.style.color = "#222";

    return () => {
      document.title = prevTitle;
      html.className = prevHtmlClass;
      body.className = prevBodyClass;
      html.style.background = prevHtmlBg;
      html.style.color = prevHtmlColor;
      body.style.background = prevBodyBg;
      body.style.color = prevBodyColor;
    };
  }, []);

  return (
    <div
      data-testid="fake-500"
      style={{
        fontFamily: "Tahoma, Geneva, Verdana, sans-serif",
        background: "#f0f0f0",
        color: "#222",
        minHeight: "100vh",
        margin: 0,
        padding: "48px 24px",
      }}
    >
      <h1 style={{ fontSize: "24px", fontWeight: "normal", margin: "0 0 12px" }}>
        500 Internal Server Error
      </h1>
      <p style={{ margin: "0 0 8px", fontSize: "14px" }}>
        The server encountered an internal error and was unable to complete your
        request.
      </p>
      <p style={{ margin: 0, fontSize: "14px", color: "#555" }}>
        Please try again later.
      </p>
      <hr style={{ margin: "24px 0", border: "none", borderTop: "1px solid #ccc" }} />
      <p style={{ margin: 0, fontSize: "12px", color: "#777" }}>nginx</p>
    </div>
  );
}
