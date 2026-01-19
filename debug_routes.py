import sys
import os

# Add current directory to path so we can import main
sys.path.append(os.getcwd())

try:
    from main import app
    print("Successfully imported app from main")
    
    found = False
    for route in app.routes:
        if hasattr(route, "path") and route.path == "/api/auth/google":
            print(f"FOUND ROUTE: {route.path} [{','.join(route.methods)}]")
            found = True
            
    if not found:
        print("ROUTE NOT FOUND: /api/auth/google")
        print("All routes:")
        for route in app.routes:
            if hasattr(route, "path"):
                print(f" - {route.path}")

except Exception as e:
    print(f"Error importing app: {e}")
