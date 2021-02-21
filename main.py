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

import config as CONFIG

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

    days_range = CONFIG.days_range # Number of days, from events would be loaded (0 - all)
    google_calendar_ids = CONFIG.google_calendar_ids
    notion_token_v2 = CONFIG.notion_token_v2
    notion_table = CONFIG.notion_table
    notion_date_prop = CONFIG.notion_date_prop
    notion_cal_prop = CONFIG.notion_cal_prop
    notion_del_prop = CONFIG.notion_del_prop
    timezone = CONFIG.timezone

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
                days_delta = (new_event["end"] - new_event["start"]).days
                if(days_delta > 1):
                    new_event["start"] = datetime.date(new_event["start"].year, new_event["start"].month, new_event["start"].day)
                    new_event["end"] = datetime.date(new_event["end"].year, new_event["end"].month, new_event["end"].day)
                # date1, date1 + 1
                if(days_delta == 1):
                    new_event["start"] = datetime.date(new_event["start"].year, new_event["start"].month, new_event["start"].day)
                    new_event["end"] = None
                # date1, date1
                if(new_event["start"] == new_event["end"]):
                    new_event["start"] = datetime.date(new_event["start"].year, new_event["start"].month, new_event["start"].day)
                    new_event["end"] = None

                # date1, date2

            else:
                # datetime1, datetime1
                delta_minutes = (new_event["end"] - new_event["start"]).seconds / 60
                if (new_event["start"] == new_event["end"] or delta_minutes <= 15):
                    new_event["end"] = None
                # datetime1, datetime2

            new_event["updated"] = parse(gevent["updated"].split('.')[0])
            new_event["calendar"] = cal_name

            if gevent["status"] == "canceled":
                new_event["deleted"] = True
            else:
                new_event["deleted"] = False

            google_events.append(new_event)
            CONFIG.DEBUG
            #print("Google ==> " + str(new_event["calendar"] + " | "+str(new_event["title"])))
    google_events_ids = [x['id'] for x in google_events]
    #print("Google events amount:" + str(len(google_events_ids)))

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
        if getattr(nevent, notion_date_prop) == None:
            new_event["start"] = None
            new_event["end"] = None
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
                    if (new_event["start"] == new_event["end"] or delta_minutes <= 15):
                        new_event["end"] = None
                    # datetime1, datetime2
                    
        if not hasattr(nevent, notion_cal_prop):
            new_event["calendar"] = ""
        else:
            new_event["calendar"] = getattr(nevent, notion_cal_prop)

        new_event["updated"] = nevent.Last_Edited
        deleted = getattr(nevent, notion_del_prop)

        if deleted == False or deleted == '' or deleted == None:
            new_event["deleted"] = False
        else:
            new_event["deleted"] = True
            
        notion_events.append(new_event)
        #print("Notion ==> " + str(new_event["calendar"]) + " | "+str(new_event["title"]))
    notion_events_ids = [x["id"] for x in notion_events]
    #print("Notion events amount:" + str(len(notion_events_ids)))

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
        if nev["id"] not in google_events_ids and nev["start"] != None and nev["calendar"] != None and not nev["deleted"]:
            add_to_google.append(nev)
    #print("Add to Google: " + str(len(add_to_google)))
    for gev in google_events:
        if gev["id"] not in notion_events_ids and not gev["deleted"]:
            add_to_notion.append(gev)
    #print("Add to Notion: " + str(len(add_to_notion)))
    for nev in notion_events:
        for gev in google_events:
            if (gev["id"] == nev["id"]):
                # later = larger
                if(gev["updated"] > nev["updated"] and not gev["deleted"]):
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
                        print(f"N UPDATE [{nev['title']}]")
                        update_in_notion.append(gev)

                if(gev["updated"] < nev["updated"] and not nev["deleted"]):
                    g_update = False
                    field = "title"
                    if(gev[field] != nev[field]):
                        g_update = True
                        print(f"G UPDATE [{field}]: {gev['title']} -> {nev['title']}")
                    field = "start"
                    if(gev[field] != nev[field]):
                        g_update = True
                        print(f"G UPDATE [{field}]: {gev['start']} -> {nev['start']}")
                    field = "end"
                    if(gev[field] != nev[field]):
                        g_update = True
                        print(f"G UPDATE [{field}]: {gev['end']} -> {nev['end']}")
                    field = "calendar" 
                    if(gev[field] != nev[field]):
                        g_update = True
                        print(f"G UPDATE [{field}]: {gev['calendar']} -> {nev['calendar']}")

                    if g_update:
                        print(f"G UPDATE [{nev['title']}]")
                        update_in_google.append(gev)

                if (gev["updated"] > nev["updated"] and gev["deleted"] == True and nev["deleted"] == False):
                    print(f"N DELETE [{nev['title']}] {nev['id']}")
                    delete_from_notion.append(gev)

                if (gev["updated"] < nev["updated"] and nev["deleted"] == True and gev["deleted"] == False):
                    print(f"G DELETE [{gev['title']}] {gev['id']}")
                    delete_from_google.append(nev)
        
    # print("Update in Google: " + str(len(update_in_google)))
    # print("Update in Notion: " + str(len(update_in_notion)))
    # print("Delete from Google: " + str(len(delete_from_google)))
    # print("Delete from Notion: " + str(len(delete_from_notion)))

    # SYNC DATA
    # ====================================================================================================

    #TODO: How to find in this NotionCollection
    
    for event in add_to_notion:
        identifier = notion_add_event(cv, service, event)
        print(identifier)

    for event in add_to_google:
        identifier = google_add_event(service, event)

    for nevupd in update_in_notion:
            for nev in notion_res:
                if nev.id.replace("-","000") == nevupd["id"]:
                    notion_update_event(nev, nevupd)
                    a=1

    for gevupd in update_in_google:
            for gev in google_events:
                if gev["id"] == gevupd["id"]:
                    google_update_event(service, gev, gevupd)

    for gevdel in delete_from_google:
        google_delete_event(service, gevdel)

    for nevdel in delete_from_notion:
        for nev in notion_res:
            if nev.id.replace("-","000") == nevdel["id"]:
               a = 1
               notion_delete_event(nev)


    #print("Script reached the end")


def notion_add_event(notion_client, google_client, event):

    n_date = NotionDate(event["start"])
    n_date.end = event["end"]

    try:
        notion_event = notion_client.collection.add_row()
        notion_event.name = event["title"]
        setattr(notion_event, notion_date_prop, n_date)
        setattr(notion_event, notion_cal_prop, event["calendar"])

        print(
            f"N ADD: {event['calendar']} | {event['title']} - {event['start']} to {event['end']}")

    except Exception as e:
        print(e)

    nevent_id = str(notion_event.id.replace("-", "000"))
    event_body = google_client.events().get(calendarId=google_calendar_ids[event["calendar"]],
                                        eventId=event["id"]).execute()

    event_body["id"] = nevent_id
    del event_body["iCalUID"]
    if 'recurringEventId' in event_body:    
        del event_body['recurringEventId']

    try:
        google_client.events().delete(calendarId=google_calendar_ids[event["calendar"]],
                                    eventId=event["id"]).execute()
        event_body_new = google_client.events().insert(
            calendarId=google_calendar_ids[event["calendar"]], body=event_body).execute()
    except Exception as e:
            print(e)

    print(f"N Update DONE {event['title']}")
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
            start = datetime.date(_event["start"].year,_event["start"].month,_event["start"].day)
            end = (start + datetime.timedelta(days=1))
            key = "date"
        # 3
        if (isinstance(_event["start"],datetime.datetime)):
            start = _event["start"]
            end = _event["start"] + datetime.timedelta(minutes=15)
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
            end = _event["end"]
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
    try:
        event = google_client.events().insert(calendarId=google_calendar_ids[_event["calendar"]], body=event_body).execute()
        event = google_client.events().update(calendarId=google_calendar_ids[_event["calendar"]],
                                        eventId=_event["id"], body=event).execute()
        print(
            f"G ADD DONE: {_event['calendar']} | {_event['title']} - {start} to {end}")
    except Exception as e:
        print(e)
        return None
    
    return event

def notion_update_event(notion_event, event):
    n_date = None

    # date - x - All day event
    # date - date - Many days event`
    # datetime - x - Not impossible with google events
    # datetime - datetime - regular

    n_date = NotionDate(event["start"])
    n_date.end = event["end"]

    try:
        notion_event.name  = event["title"]
        setattr(notion_event, notion_date_prop, n_date)
        setattr(notion_event, notion_cal_prop, event["calendar"])
        print(f"N Update DONE {event['title']}")

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
            start = datetime.date(_event["start"].year,_event["start"].month,_event["start"].day)
            end = (start + datetime.timedelta(days=1))
            key = "date"
        # 3
        if (isinstance(_event["start"],datetime.datetime)):
            start = _event["start"]
            end = _event["start"] + datetime.timedelta(minutes=15)
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

    if (_event["calendar"] != gevent["calendar"]):
        try:
            google_client.events().delete(calendarId=google_calendar_ids[gevent["calendar"]],eventId=gevent["id"]).execute()
            event = google_client.events().insert(calendarId=google_calendar_ids[_event["calendar"]], body=event_body).execute()
            print(f"G Update DONE {_event['title']}")
        except Exception as e:
            print(e)
            return None
    else:
        try:
            event = google_client.events().update(calendarId=google_calendar_ids[gevent["calendar"]],
                                            eventId=_event["id"], body=event_body).execute()
            print(f"G Update DONE {_event['title']}")                 
        except Exception as e:
            print(e)
            return None
    
    return event


def google_delete_event(google_client, _event):

    try:
        google_client.events().delete(calendarId=google_calendar_ids[_event["calendar"]],
                                    eventId=_event["id"]).execute()
        print(f"G DELETE DONE {_event['title']}")         
    except Exception as e:
        print(e)
        return False
    return True

def notion_delete_event(nevent):

    try:
        setattr(nevent, notion_del_prop, "Deleted by google")
        print(f"N DELETE DONE {nevent['title']}")         

    except Exception as e:
        print(e)
        return False
    return True


if __name__ == "__main__":
    if os.path.exists('token.pickle'):
        main()
    else:
        gcal_auth()