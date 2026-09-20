declare module "swagger-ui-dist/swagger-ui-bundle.js" {
  export type SwaggerRequest = {
    url: string;
    headers?: Record<string, string>;
  };

  export type SwaggerUI = {
    destroy?: () => void;
  };

  export default function SwaggerUIBundle(opts: {
    domNode: HTMLElement;
    url: string;
    requestInterceptor?: (req: SwaggerRequest) => SwaggerRequest;
    persistAuthorization?: boolean;
    tryItOutEnabled?: boolean;
    filter?: boolean | string;
    deepLinking?: boolean;
    docExpansion?: "list" | "full" | "none";
    defaultModelsExpandDepth?: number;
    displayRequestDuration?: boolean;
  }): SwaggerUI;
}

declare module "swagger-ui-dist/swagger-ui.css";
