// Define the types for your environment variables and bindings
export interface Env {
  DOCS_USERNAME?: string;
  DOCS_PASSWORD?: string;
  // This binding allows the worker to fetch from the static assets
  ASSETS: Fetcher; 
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const USERNAME = env.DOCS_USERNAME;
    const PASSWORD = env.DOCS_PASSWORD; 

    // Safety check: Ensure secrets are configured
    if (!USERNAME || !PASSWORD) {
      return new Response('Server configuration error: Secrets are not set.', { status: 500 });
    }

    // Extract the Authorization header
    const authHeader = request.headers.get('Authorization');

    // Helper function to prompt for credentials
    const requireAuth = (): Response => {
      return new Response('Unauthorized', {
        status: 401,
        headers: {
          'WWW-Authenticate': 'Basic realm="Secure Documentation"',
        },
      });
    };

    if (!authHeader) {
      return requireAuth();
    }

    // Validate the credentials
    try {
      const base64 = authHeader.split(' ')[1];
      const decoded = atob(base64);
      const [username, password] = decoded.split(':');

      if (username !== USERNAME || password !== PASSWORD) {
        return requireAuth();
      }
    } catch (e) {
      return requireAuth();
    }

    // If authentication is successful, serve the HonKit static assets
    return env.ASSETS.fetch(request);
  },
};