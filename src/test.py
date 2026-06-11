from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore

model_name = "mistralai/Mistral-7B-Instruct-v0.1"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(model_name)


def generate_response(prompt, max_length=100):
    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        padding=True,
        truncation=True,
    )
    outputs = model.generate(**inputs, max_length=max_length)
    return tokenizer.decode(outputs[0], skip_special_tokens=True)


# Ejemplo de uso
spanish_prompt = "¿Cuál es la capital de Francia?"
english_prompt = "What is the capital of France?"

print(generate_response(spanish_prompt))
print(generate_response(english_prompt))
