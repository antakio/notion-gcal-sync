from __future__ import print_function
import datetime
from dateutil.parser import parse
import pickle
import os
import errno
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from notion.client import NotionClient
from notion.collection import NotionDate

# If modifying these scopes, delete the file token.pickle.
SCOPES = ["https://www.googleapis.com/auth/calendar"]


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

    # PREP DATA
    # ====================================================================================================
    global creds
    global google_calendar_ids
    global timezone
    global notion_table
    global notion_date_prop
    global notion_cal_prop
    global notion_del_prop

    days_range = 0  # Number of days, from events would be loaded (0 - all)
    google_calendar_ids = {
        "Work": "38ubqlt9barnad61d81cpinj4s@group.calendar.google.com",
        "Family": "9js0btqfg3vt88cm62cafqfhgs@group.calendar.google.com",
        #   "NameOfCalendar" : "calendar ID"
    }
    MULTICALMODE = (len(google_calendar_ids) > 1)
    notion_token_v2 = "f2282d5d6a0776908ed44507033636e34bb871450db8af9d4aaddd5d622238524983c78f77dc09178e9e900bc3de3502f40bdefa78a850321e39b3e45a09ca1107b3bbd9a624bf059bd19da18cd9"
    notion_table = "https://www.notion.so/andreirbkn/e51e40bbc4a740dea8b31b9935a0455c?v=f4ba657e5a074e9aa5f21e1fc664f0a9"
    notion_date_prop = "Target Date"
    notion_cal_prop = "Calendar"
    notion_del_prop = "Archive"
    timezone = "Asia/Yekaterinburg"

    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    service = build("calendar", "v3", credentials=creds)

    # Call the Google API
    # ====================================================================================================

    timeMin = None
    timeRange = None
    if days_range > 0:
        timeRange = (datetime.datetime.utcnow() - datetime.timedelta(days=days_range)
                    )
        timeMin = (datetime.datetime.utcnow() - datetime.timedelta(days=days_range)
                ).isoformat() + "Z"  # "Z" indicates UTC time
    google_res = {}

    # get gcal rows by each calendar
    try:
        for calendar_name, calendar_id in google_calendar_ids.items():
            events_result = service.events().list(calendarId=calendar_id,
                                                  timeMin=timeMin,
                                                  # maxResults=2048,
                                                  singleEvents=True,
                                                  orderBy="startTime").execute()
            google_res[calendar_name] = events_result.get("items", [])
    except Exception as e:
        print(e)

    google_events = []
    for cal_name, res_events in google_res.items():
        for gevent in res_events:

            if "description" not in gevent:
                gevent["description"] = ""
            new_event = {}
            new_event["id"] = gevent["id"]
            new_event["title"] = gevent["summary"]
            new_event["description"] = gevent["description"]

            # datetime1, datetime2
            new_event["start"] = parse(next(iter(gevent["start"].values())))
            new_event["end"] = parse(next(iter(gevent["end"].values())))

            new_event["start"] = datetime.datetime(new_event["start"].year, new_event["start"].month, new_event["start"].day, new_event["start"].hour, new_event["start"].minute, new_event["start"].second)
            new_event["end"] = datetime.datetime(new_event["end"].year, new_event["end"].month, new_event["end"].day, new_event["end"].hour, new_event["end"].minute, new_event["end"].second)

            #all day events
            if (new_event["start"].hour == 0 and new_event["start"].minute == 0
            and new_event["end"].hour == 0 and new_event["end"].minute == 0):
                # date1, date1
                if(new_event["start"] == new_event["end"]):
                    new_event["start"] = datetime.date(new_event["start"].year, new_event["start"].month, new_event["start"].day)
                    new_event["end"] = None
                # date1, date1 + 1
                days_delta = (new_event["end"] - new_event["start"]).days
                if(days_delta == 1):
                    new_event["start"] = datetime.date(new_event["start"].year, new_event["start"].month, new_event["start"].day)
                    new_event["end"] = None
                # date1, date2
                if(days_delta > 1):
                    new_event["start"] = datetime.date(new_event["start"].year, new_event["start"].month, new_event["start"].day)
                    new_event["end"] = datetime.date(new_event["end"].year, new_event["end"].month, new_event["end"].day)
            else:
                # datetime1, datetime1
                delta_minutes = (new_event["end"] - new_event["start"]).seconds / 60
                if (new_event["start"] == new_event["end"] or delta_minutes < 15):
                    new_event["end"] = None
                # datetime1, datetime2

            new_event["updated"] = parse(gevent["updated"].split('.')[0])
            new_event["calendar"] = cal_name

            if gevent["status"] == "canceled":
                new_event["deleted"] = True
            else:
                new_event["deleted"] = False

            google_events.append(new_event)
            print("Google ==> " +
                  str(new_event["calendar"] + " | "+str(new_event["title"])))
    google_events_ids = [x['id'] for x in google_events]
    print("Google events amount:" + str(len(google_events_ids)))

    # Call the Notion API
    # ====================================================================================================
    client = NotionClient(token_v2=notion_token_v2)
    cv = client.get_collection_view(notion_table)

    # Run a "filtered" query (inspect network tab in browser for examples, on queryCollection calls)
    
    filter_params = ''
    if days_range > 0:
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

    # get rows from notion table
    try:
        notion_res = cv.build_query(filter=filter_params).execute()
    except Exception as e:
        print(e)

    notion_events = []
    for nevent in notion_res:
        new_event = {}
        new_event["id"] = nevent.id.replace("-", "000")
        new_event["title"] = nevent.name

        # new_event Target_Date  = nevent Target Date
        if not hasattr(nevent, notion_date_prop):
            new_event[notion_date_prop] = None
        else:
            new_event["start"] = getattr(getattr(nevent, notion_date_prop), "start")
            new_event["end"] = getattr(getattr(nevent, notion_date_prop), "end")

            # date/datetime, None


            if new_event["end"] == None:
                # date1, None
                if isinstance(new_event["start"], datetime.date):
                    a = 'a'
                # datetime1, None
                else:
                    b = 'b'

            # date/datetime, date/datetime
            else:
                # date, date
                if isinstance(new_event["start"], datetime.date):
                    # date1, date1
                    if (new_event["start"] == new_event["end"]):
                        new_event["end"] = None
                    # date1, date2
                # datetime, datetime
                else:
                    # datetime1, datetime1
                    delta_minutes = (new_event["end"] - new_event["start"]).seconds / 60
                    if (new_event["start"] == new_event["end"] or delta_minutes < 15):
                        new_event["end"] = None
                    # datetime1, datetime2
                    
        if not hasattr(nevent, notion_cal_prop):
            new_event["calendar"] = ""
        else:
            new_event["calendar"] = getattr(nevent, notion_cal_prop)

        new_event["updated"] = nevent.Last_Edited
        new_event["deleted"] = getattr(nevent, notion_del_prop)

        notion_events.append(new_event)
        print("Notion ==> " +
              str(new_event["calendar"]) + " | "+str(new_event["title"]))
    notion_events_ids = [x["id"] for x in notion_events]
    print("Notion events amount:" + str(len(notion_events_ids)))

    # SORT DATA
    # ====================================================================================================
    add_to_notion = []  # gev.id not in nevs
    add_to_google = []  # nev.id not in gevs and nev.start not null and nev.cal not null
    update_in_notion = []  # nev.id == gev.id and gev.upd < nev.upd
    update_in_google = []  # gev.id == nev.id and gev.upd > nev.upd
    # nev.id == gev.id and gev.stat == canceled and gev.upd > nev.upd
    delete_from_notion = []
    # nev.id == gev.id and nev.stat == canceled and gev.upd < nev.upd
    delete_from_google = []

    for nev in notion_events:
        if nev["id"] not in google_events_ids and nev["start"] != None and nev["calendar"] != None:
            add_to_google.append(nev)
    #print("Add to Google: " + str(len(add_to_google)))
    for gev in google_events:
        if gev["id"] not in notion_events_ids:
            add_to_notion.append(gev)
    #print("Add to Notion: " + str(len(add_to_notion)))
    for nev in notion_events:
        for gev in google_events:
            if (gev["id"] == nev["id"]):
                # later = larger
                if(gev["updated"] > nev["updated"]):
                    n_update = False
                    field = "title"
                    if(gev[field] != nev[field]):
                        n_update = True
                        print(f"N UPDATE [{field}]: {nev['title']} -> {gev['title']}")
                    field = "start"
                    if(gev[field] != nev[field]):
                        n_update = True
                        print(f"N UPDATE [{field}]: {nev['start']} -> {gev['start']}")
                    field = "end"
                    if(gev[field] != nev[field]):
                        n_update = True
                        print(f"N UPDATE [{field}]: {nev['end']} -> {gev['end']}")
                    field = "calendar" 
                    if(gev[field] != nev[field]):
                        n_update = True
                        print(f"N UPDATE [{field}]: {nev['calendar']} -> {gev['calendar']}")

                    if n_update:
                        update_in_notion.append(gev)

                if(gev["updated"] < nev["updated"]):
                    g_update = False
                    field = "title"
                    if(gev[field] != nev[field]):
                        g_update = True
                        print(f"G UPDATE [{field}]: {nev['title']} -> {gev['title']}")
                    field = "start"
                    if(gev[field] != nev[field]):
                        g_update = True
                        print(f"G UPDATE [{field}]: {nev['start']} -> {gev['start']}")
                    field = "end"
                    if(gev[field] != nev[field]):
                        g_update = True
                        print(f"G UPDATE [{field}]: {nev['end']} -> {gev['end']}")
                    field = "calendar" 
                    if(gev[field] != nev[field]):
                        g_update = True
                        print(f"G UPDATE [{field}]: {nev['calendar']} -> {gev['calendar']}")

                    if g_update:
                        update_in_google.append(gev)

                if (gev["updated"] > nev["updated"] and gev["deleted"] == "canceled"):
                    delete_from_notion.append(gev)

                if (gev["updated"] < nev["updated"] and (nev["deleted"] == True or nev["deleted"] != None)):
                    delete_from_google.append(nev)
        
    print("Update in Google: " + str(len(update_in_google)))
    print("Update in Notion: " + str(len(update_in_notion)))
    print("Delete from Google: " + str(len(delete_from_google)))
    print("Delete from Notion: " + str(len(delete_from_notion)))

    # SYNC DATA
    # ====================================================================================================

    #TODO: How to find in this NotionCollection
    
    # for event in add_to_notion:
    #     identifier = notion_add_event(cv, service, event)
    #     print(identifier)

    # for event in add_to_google:
    #     identifier = google_add_event(service, event)

    # for nevupd in update_in_notion:
    #         for nev in notion_res:
    #             if nev.id.replace("-","000") == nevupd["id"]:
    #                 notion_update_event(nev, nevupd, notion_date_prop, notion_cal_prop)

    # for gevupd in update_in_google:
    #         for gev in google_events:
    #             if gev["id"] == gevupd["id"]:
    #                 google_update_event(service, gev, gevupd)

    print("Script reached the end")


def notion_add_event(notion_client, google_client, event):

    n_date = None

    # date - x - All day event
    # date - date - Many days event
    # datetime - x - Not impossible with google events
    # datetime - datetime - regular

    # Google All day check
    if (isinstance(event["start"],datetime.datetime)) and (event["start"].hour == 0 and event["start"].minute == 0 
                                                      and event["end"].hour == 0 and event["end"].minute == 0):
        if (event["end"] - event["start"]).days > 1:
            # Many days event
            n_date = NotionDate(event["start"].date())
            n_date.end = event["end"].date()
        else:
            # All day event
            n_date = NotionDate(event["start"].date())
            n_date.end = None
    # Regular
    else:
        n_date = NotionDate(event["start"])
        n_date.end = event["end"]

    try:
        notion_event = notion_client.collection.add_row()
        notion_event.name = event["title"]
        setattr(notion_event, notion_date_prop, n_date)
        setattr(notion_event, notion_cal_prop, event["calendar"])

        print(
            f"NOTION ADD: {event['calendar']} | {event['title']} - {event['start']} to {event['end']}")

    except Exception as e:
        print(e)

    nevent_id = str(notion_event.id.replace("-", "000"))
    event_body = google_client.events().get(calendarId=google_calendar_ids[event["calendar"]],
                                        eventId=event["id"]).execute()

    event_body["id"] = nevent_id
    del event_body["iCalUID"]
    if 'recurringEventId' in event_body:    
        del event_body['recurringEventId']

    google_client.events().delete(calendarId=google_calendar_ids[event["calendar"]],
                                  eventId=event["id"]).execute()
    event_body_new = google_client.events().insert(
        calendarId=google_calendar_ids[event["calendar"]], body=event_body).execute()

    return notion_event

def google_add_event(google_client, _event):
   
    #1 date - x - All day event -> start 0 0 start+1d 0 0
    #2 date - date - Many days event -> start end
    #3 datetime - x - Not impossible with google events -> start start
    #4 datetime - datetime - regular -> start start

    start = ""
    end = ""
    key = ""
    # 1 3
    if _event["end"] == None:
        # 1
        if (isinstance(_event["start"],datetime.date)):
            start = datetime.datetime(_event["start"].year,_event["start"].month,_event["start"].day)
            end = (start + datetime.timedelta(days=1))
            key = "date"
        # 3
        if (isinstance(_event["start"],datetime.datetime)):
            start = _event["start"]
            end = _event["end"]
            key = "dateTime"
    # 2 4
    else:
        #2
        if (isinstance(_event["start"],datetime.date)):
            start = _event["start"]
            end = _event["end"]
            key = "date"
        #4
        if (isinstance(_event["start"],datetime.datetime)):
            start = _event["start"]
            end = _event["start"]
            key = "dateTime"

    start = str(start).replace(" ", "T")
    end = str(end).replace(" ", "T")

    event_body = {
            "end": {
                key : end,
                "timeZone": timezone
            },
            "start": {
                key : start,
                "timeZone": timezone
            },
            "summary": _event["title"],
            "id": _event["id"]
        }

    print(f"GOOGLE CREATE - TITLE: {_event['title']}")
    print(f"GOOGLE CREATE - START: {start}")
    print(f"GOOGLE CREATE - END: {end}")

    try:
        event = google_client.events().insert(calendarId=google_calendar_ids[_event["calendar"]], body=event_body).execute()
        print(f"GOOGLE CREATE")
        event = google_client.events().update(calendarId=google_calendar_ids[_event["calendar"]],
                                        eventId=_event["id"], body=event).execute()
        print("GOOGLE UPDATE")
    except Exception as e:
        print(e)
        return None
        # the only way to end up here is by clearing your trash
        # (do not do because it eliminates Notion IDs from the usable pool)
        # print(f"Please make a new event in notion for {name}, it won't work since you emptied your trash!")
    
    return event

def notion_update_event(notion_event, event):
    n_date = None

    # date - x - All day event
    # date - date - Many days event`
    # datetime - x - Not impossible with google events
    # datetime - datetime - regular

    # Google All day check
    if (isinstance(event["start"],datetime.datetime)) and (event["start"].hour == 0 and event["start"].minute == 0 and event["start"].second == 0 and event["end"].hour == 0 and event["end"].minute == 0 and event["end"].second == 0):
        if (event["end"] - event["start"]).days > 1:
            # Many days event
            n_date = NotionDate(event["start"].date())
            n_date.end = event["end"].date()
        else:
            # All day event
            n_date = NotionDate(event["start"].date())
            n_date.end = None
    # Regular
    else:
        n_date = NotionDate(event["start"])
        n_date.end = event["end"]

    try:
        if (notion_event.name != event["title"]):
            notion_event.name = event["title"]
            print(f"TITLE UPD: {notion_event.name} -> {event['title']}")
        if (getattr(notion_event, notion_date_prop) != n_date):
            setattr(notion_event, notion_date_prop, n_date)
            print(f"DATE UPD: {getattr(notion_event, notion_date_prop)} -> {n_date}")
        if(getattr(notion_event, notion_cal_prop) != event["calendar"]):
            setattr(notion_event, notion_cal_prop, event["calendar"])
            print(f"DATE UPD: {getattr(notion_event, notion_date_prop)} -> {n_date}")
        print(
            f"NOTION ADD: {event['calendar']} | {event['title']} - {event['start']} to {event['end']}")

    except Exception as e:
        print(e)
        return None

    return notion_event
def google_update_event(google_client, gevent, _event):

    #1 date - x - All day event -> start 0 0 start+1d 0 0
    #2 date - date - Many days event -> start end
    #3 datetime - x - Not impossible with google events -> start start
    #4 datetime - datetime - regular -> start start

    start = ""
    end = ""
    key = ""
    # 1 3
    if _event["end"] == None:
        # 1
        if (isinstance(_event["start"],datetime.date)):
            start = datetime.datetime(_event["start"].year,_event["start"].month,_event["start"].day)
            end = (start + datetime.timedelta(days=1))
            key = "date"
        # 3
        if (isinstance(_event["start"],datetime.datetime)):
            start = _event["start"]
            end = _event["end"]
            key = "dateTime"
    # 2 4
    else:
        #2
        if (isinstance(_event["start"],datetime.date)):
            start = _event["start"]
            end = _event["end"]
            key = "date"
        #4
        if (isinstance(_event["start"],datetime.datetime)):
            start = _event["start"]
            end = _event["start"]
            key = "dateTime"

    start = str(start).replace(" ", "T")
    end = str(end).replace(" ", "T")

    event_body = {
            "end": {
                key : end,
                "timeZone": timezone
            },
            "start": {
                key : start,
                "timeZone": timezone
            },
            "summary": _event["title"],
            "id": _event["id"]
        }

    print(f"GOOGLE UPDATE - TITLE: {_event['title']}")
    print(f"GOOGLE UPDATE - START: {start}")
    print(f"GOOGLE UPDATE - END: {end}")

    if (_event["calendar"] != gevent["calendar"]):
        try:
            google_client.events().delete(calendarId=google_calendar_ids[gevent["calendar"]],eventId=gevent["id"]).execute()
            event = google_client.events().insert(calendarId=google_calendar_ids[_event["calendar"]], body=event_body).execute()
        except Exception as e:
            print(e)
            return None
    else:
        try:
            event = google_client.events().update(calendarId=google_calendar_ids[gevent["calendar"]],
                                            eventId=_event["id"], body=event_body).execute()
            print("GOOGLE UPDATE")
        except Exception as e:
            print(e)
            return None
            # the only way to end up here is by clearing your trash
            # (do not do because it eliminates Notion IDs from the usable pool)
            # print(f"Please make a new event in notion for {name}, it won't work since you emptied your trash!")
    
    return event


if __name__ == "__main__":
    if os.path.exists('token.pickle'):
        main()
    else:
        gcal_auth()