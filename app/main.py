import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from orquesta_sdk import Orquesta, OrquestaClientOptions
from openpyxl import load_workbook
from dotenv import load_dotenv

load_dotenv()

# Initialize FastAPI app
app = FastAPI()

# Set up CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Initialize Orquesta client
def init_orquesta_client():
    api_key = os.getenv("ORQUESTA_API_KEY")
    options = OrquestaClientOptions(api_key=api_key, environment="production")
    return Orquesta(options)

client = init_orquesta_client()


def load_questions_from_sheet(sheet_path):
    questions_with_options = []
    workbook = load_workbook(sheet_path)
    sheet = workbook.active
    for row in sheet.iter_rows(min_row=0, values_only=True):  # Assuming row 1 has the headers
        question = row[0]  # Question is in the first column
        quick_reply_options = []
        if row[1]:  # Check if there are quick reply options in the second column
            # Split options on semicolon and strip whitespace
            quick_reply_options = [option.strip() for option in row[1].split(';')]
        
        if question:
            # We will not use question_index or condition as they are not present in the Excel file
            questions_with_options.append((None, question, quick_reply_options, None))
    print(questions_with_options)
    return questions_with_options


# Load the questions and options when the app starts
questions_with_options = load_questions_from_sheet("data/Firm24_lijst.xlsx")
@app.post("/question/")
async def question(request: Request):
    data = await request.json()
    question_index = data.get("question_index")
    previous_question = data.get("previous_question")
    previous_answer = data.get("previous_answer")
    chatbot_state = data.get("chatbot_state", "ASKING_QUESTION")  # Default state is ASKING_QUESTION

    if chatbot_state == "ASKING_QUESTION":
        evaluation_deployment = client.deployments.invoke(
            key="Firm24-evaluate-user-input",
            context={"environments": []},
            inputs={"previous_question": previous_question, "user_input": previous_answer}
        )
        evaluation_result = evaluation_deployment.choices[0].message.content

        if evaluation_result == "No":
            clarification_deployment = client.deployments.invoke(
                key="Firm24-handle-clarification",
                context={"environments": []},
                inputs={"previous_question": previous_question, "user_input": previous_answer}
            )
            clarification_response = clarification_deployment.choices[0].message.content
            return {"rephrased_question": clarification_response, "quick_reply_options": [], "chatbot_state": "CLARIFYING_ANSWER"}

    # Proceed with next question or continue clarification based on the state
    if chatbot_state in ["CLARIFYING_ANSWER", "Yes"]:
        if question_index is None or question_index < 1 or question_index > len(questions_with_options):
            raise HTTPException(status_code=400, detail="Invalid question index")

        # Assuming questions_with_options is a list of tuples (index, question, options, condition)
        question = questions_with_options[question_index - 1][1]  # Adjust indexing as needed
        quick_reply_options = questions_with_options[question_index - 1][2]  # Adjust indexing as needed

        # If clarification was handled, reset state to ask next question
        chatbot_state = "ASKING_QUESTION" if chatbot_state == "CLARIFYING_ANSWER" else chatbot_state

        deployment = client.deployments.invoke(
            key="Firm24_vragenlijst",
            context={"environments": []},
            inputs={"question": question, "previous": f"Vraag: {previous_question}\nAntwoord: {previous_answer}"}
        )
        rephrased_question = deployment.choices[0].message.content

        return {
            "rephrased_question": rephrased_question,
            "quick_reply_options": quick_reply_options,
            "chatbot_state": chatbot_state,
            "question_index": question_index + 1  # Prepare index for next question
        }

    # In case of unexpected state, provide a generic error message
    return {"error": "Unexpected chatbot state", "chatbot_state": chatbot_state}


def is_condition_met(condition, previous_answer, combined_questions_with_options):
    condition_question_index, valid_answers = condition.split('=')
    # Split the valid answers by comma to support multiple valid answers
    valid_answers_list = valid_answers.split(',')
    # No need to adjust for zero-based indexing if your question indices already start at 1
    return previous_answer in valid_answers_list

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
