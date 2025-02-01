from openai import OpenAI, OpenAIError
import json

def test_api_key(api_key):
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.openai.com/v1"  # Explicitly set the base URL
    )
    
    print(f"\nAPI Configuration:")
    print(f"API Key: {api_key[:8]}...{api_key[-4:]}")
    print("API Key type:", "Project-scoped" if api_key.startswith("sk-proj-") else "Standard")
    
    try:
        # First try to list available models
        print("\nTesting models access...")
        try:
            models = client.models.list()
            print("Available models:", [model.id for model in models.data])
        except Exception as e:
            print("Error listing models:", str(e))
            print("Raw response:", getattr(e, 'response', None))
        
        # Then try a minimal completion
        print("\nTesting chat completion...")
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=5
            )
            print("Chat completion response:", response.choices[0].message.content)
        except Exception as e:
            print("Error in chat completion:", str(e))
            print("Raw response:", getattr(e, 'response', None))
        
        return True
    except Exception as e:
        print("\nError Details:")
        print("Error type:", type(e).__name__)
        print("Error message:", str(e))
        
        # Try to get more details about the error
        if hasattr(e, 'response'):
            print("\nResponse details:")
            print("Status code:", getattr(e.response, 'status_code', None))
            print("Headers:", getattr(e.response, 'headers', None))
            try:
                print("Content:", getattr(e.response, 'content', None))
            except:
                print("Content: Unable to read response content")
        
        return False

if __name__ == "__main__":
    # Get the full API key
    api_key = input("Please enter your full OpenAI API key: ")
    test_api_key(api_key) 