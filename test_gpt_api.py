from openai import OpenAI

text = """
old on It was battle bandana 16 My dad's my dad's hair. This is what he left me. Yeah, dude when he left me when he died He le.
"""

client = OpenAI()

def get_completion(prompt, client, model="gpt-3.5-turbo"):
    messages = [{"role": "user", "content": prompt}]
    client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.1, # this is the degree of randomness of the model's output
    )
    return response.choices[0].message["content"]
    
summary=''
prompt =f"""
Your task is to extract the key details and write a summary of the dungeons and dragons session that the people in the text are playing. Please provide only a 500 word summary of the what has happened in the dungeons and dragons session.
Text: ```{text}```
"""

response = get_completion(prompt, client)

print(response)
summary+=response