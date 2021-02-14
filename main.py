from __future__ import print_function
import datetime
import pickle
import os
import errno
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from notion.client import NotionClient

# If modifying these scopes, delete the file token.pickle.
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def gcal_auth():
    global creds
    """Shows basic usage of the Google Calendar API.
    Prints the start and name of the next 10 events on the user"s calendar.
    """
    creds = None
    # The file token.pickle stores the user"s access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            filename = "credentials.json"
            flow = InstalledAppFlow.from_client_secrets_file(
                filename, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    #service = build("calendar", "v3", credentials=creds)

    # Call the Calendar API
    # now = datetime.datetime.utcnow().isoformat() + "Z" # "Z" indicates UTC time
    # print("Getting the upcoming 10 events")
    # events_result = service.events().list(calendarId="primary", timeMin=now,
    #                                     maxResults=10, singleEvents=True,
    #                                     orderBy="startTime").execute()
    # events = events_result.get("items", [])

    # if not events:
    #     print("No upcoming events found.")
    # for event in events:
    #     start = event["start"].get("dateTime", event["start"].get("date"))
    #     print(start, event["summary"])

    main()


def main():
    global creds

    days_range = 30  # Number of days, from events would be loaded
    google_calendar_ids = {
        "Work": "38ubqlt9barnad61d81cpinj4s@group.calendar.google.com",
        "Family": "9js0btqfg3vt88cm62cafqfhgs@group.calendar.google.com",
#       "NameOfCalendar" : "calendar ID" 
    }
    notion_token_v2 = "f2282d5d6a0776908ed44507033636e34bb871450db8af9d4aaddd5d622238524983c78f77dc09178e9e900bc3de3502f40bdefa78a850321e39b3e45a09ca1107b3bbd9a624bf059bd19da18cd9"
    notion_table = "https://www.notion.so/andreirbkn/e51e40bbc4a740dea8b31b9935a0455c?v=f4ba657e5a074e9aa5f21e1fc664f0a9"
    notion_date_prop = "Target Date"
    notion_cal_prop = "Calendar"

    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    service = build("calendar", "v3", credentials=creds)
    # Call the Calendar API
    timeRange = (datetime.datetime.utcnow() - datetime.timedelta(days=days_range)
                 )
    timeMin = (datetime.datetime.utcnow() - datetime.timedelta(days=days_range)
               ).isoformat() + "Z"  # "Z" indicates UTC time
    google_res = {}
    for calendar_name, calendar_id in google_calendar_ids.items():
        events_result = service.events().list(calendarId=calendar_id,
                                              timeMin=timeMin,
                                              # maxResults=2048,
                                              singleEvents=True,
                                              orderBy="startTime").execute()
        google_res[calendar_name] = events_result.get("items", [])

    google_events = []
    for cal_name, res_events in google_res.items():
        for gevent in res_events:
            if "description" not in gevent:
                gevent["description"] = ""
            new_event = {}
            new_event["id"] = gevent["id"]
            new_event["title"] = gevent["summary"]
            new_event["description"] = gevent["description"]
            new_event["start"] = gevent["start"]
            new_event["end"] = gevent["end"]
            new_event["updated"] = gevent["updated"]
            new_event["calendar"] = cal_name

            google_events.append(new_event)


#   Call the Notion API
    client = NotionClient(token_v2=notion_token_v2)
    cv = client.get_collection_view(notion_table)

    # Run a "filtered" query (inspect network tab in browser for examples, on queryCollection calls)
    filter_params = {
        "filters": [{
            "filter": {
                "value": {
                    "type": "exact",
                    "value": {"type": "date", "start_date": timeRange.strftime("%Y-%m-%d")}
                },
                "operator": "date_is_on_or_after"
            },
            "property": notion_date_prop
        }],
        "operator": "and"
    }
    notion_res = cv.build_query(filter=filter_params).execute()

    notion_events = []
    for nevent in notion_res:
        print("=====> "+str(getattr(nevent, notion_cal_prop))+" | "+str(nevent.name))
        if not hasattr(nevent, notion_date_prop):
            continue
        if not hasattr(getattr(nevent, notion_date_prop), "start"):
            continue
        if len(google_calendar_ids) > 1: # Multi calendar sync mode
            if not hasattr(nevent, notion_cal_prop):
                continue            
            if (getattr(nevent, notion_cal_prop) not in google_calendar_ids.keys()):
                continue
        print("In Range")

        new_event = {}
        new_event["id"] = nevent.id.replace("-", "000")
        new_event["title"] = nevent.name
        #new_event['description'] = ""
        start = str(getattr(getattr(nevent, notion_date_prop),"start")).replace(" ", "T")
        # start is a date
        if "T" not in start:
            new_event["start"] = datetime.datetime.strptime(start, "%Y-%m-%d")
        # start is a datetime
        else:
            new_event["start"] = datetime.datetime.strptime(start, "%Y-%m-%dT%H:%M:%S")

        # date in notion can exists without end
        if getattr(getattr(nevent, notion_date_prop),"end") != None:
            end = str(getattr(getattr(nevent, notion_date_prop),"end")).replace(" ", "T")
            # end is a date
            if "T" not in end:
                new_event["end"] = datetime.datetime.strptime(end, "%Y-%m-%d")
            # end is a datetime
            else:
                new_event["end"] = datetime.datetime.strptime(end, "%Y-%m-%dT%H:%M:%S")

        new_event["updated"] = nevent.Last_Edited
        new_event["calendar"] = getattr(nevent, notion_cal_prop)

        notion_events.append(new_event)

    print("Main reached")


if __name__ == "__main__":
    main()
else:
    gcal_auth()
