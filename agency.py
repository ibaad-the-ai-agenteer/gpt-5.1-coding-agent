from dotenv import load_dotenv
from agency_swarm import Agency
from agent2 import coding_agent as code
from coding_agent import coding_agent

import asyncio

load_dotenv()
agent2 = code()

# do not remove this method, it is used in the main.py file to deploy the agency (it has to be a method)
def create_agency(load_threads_callback=None):
    agency = Agency(
        coding_agent,
        communication_flows=[coding_agent, agent2],
        name="CodingAgency",
        shared_instructions="shared_instructions.md",
        load_threads_callback=load_threads_callback,
    )
    return agency


if __name__ == "__main__":
    agency = create_agency()

    # test 1 message
    # async def main():
    #     response = await agency.get_response("Hello, how are you?")
    #     print(response)
    # asyncio.run(main())

    # run in terminal
    agency.terminal_demo()