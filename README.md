Features:

1. ~~Email address must be unique~~ - DONE
2. ~~Student cannot book the same class more than one time~~ - DONE - to not TO DO because we are not even giving the option to the student to book it [*]
3. ~~Student cannot book more than one class taking place at the same time~~ - DONE - to not TO DO because we are not even giving the option to the student to book it [*]
4. ~~Admin cannot create a class in the past~~ - DONE
5. Admin cannot create more than one class at the same time from the same teacher - TO DO
6. Only registered user can book a class - to not TO DO because a not registered user can't even log in [*]
7. ~~Check if class exists - not TO DO because we are not even going to show it to the user~~ [*]
8. ~~Check if class is in the future - not TO DO because we are not even going to show it to the user~~ [*]
9. Admin should email all the students that have booked to the class if is cancelled by the school and remove it from the list of the classes - NICE TO HAVE
10. Admin send an email reminder 1 day before the class - NICE TO HAVE
11. ~~The student, once logged in, under /bookings has to see only the classes that has booked in the future~~ - DONE
12. ~~And under /classes only the ones in the future (also the ones that at his time of looking are fully booked since he might be interested to join~~ - DONE
13. Create an **admin** front end **page** where she can: creates a class, check the user(s) that have booked a class - to DO
14. Change errors to be meaningful for the user - TO DO

Resources:
https://claude.ai/chat/b283e5b3-12eb-424c-9375-3215423150d2
https://claude.ai/chat/5ae75e4a-c81e-42d2-ae1c-44e9ce9909a2
https://claude.ai/chat/61e93f8b-c28f-47f2-8bb3-3b4828d1c37d
https://dev.to/shubhamtiwari909/backend-filters-vs-frontend-filters-1k4a

Codeoubts:
1. ~~Why do i have to specify Booking id in line 201?~~
2. ~~Do we build the logic~~ (e.g. just show classes in the future) ~~in the backend or in the frontend?~~ 
3. Rewrite /classes/bookings from query to dict 
4. Should i move the logic = build the group by in the frontend and keep in the backend only GET classes? @lwang