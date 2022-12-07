select *
from SQL_Portfolio.dbo.noc_regions
select *
from SQL_Portfolio.dbo.athlete_events

--1.How many olympics games have been held?


select count(distinct games) as total_games
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC



--2.Mention the total no of nations who participated in each olympics game?


select distinct Games, count(distinct region) as num_region
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
group by Games



--3.Which nation has participated in all of the olympic games?


select  region,count(distinct games) as total_participated_games
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
group by region
having count(distinct games) = (select  top 1 count(distinct games)
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
order by count(distinct games))


--4.Identify the sport which was played in all summer olympics.


select Sport, count(distinct Games) as no_of_games
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
where Season = 'Summer' 
group by sport
having  count(distinct Games) = (select  count(distinct Games)
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
where Season = 'Summer')




--5.Fetch details of the oldest athletes to win a gold medal.


select *
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
where Medal = 'Gold' and age = (select max(age) 
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
where Medal = 'Gold'
)


--6. Find the Ratio of male and female athletes participated in all olympic games.


with ctem as
(select count(Sex) as male
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
where Sex = 'M') ,
ctef as
(select count(Sex) as female
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
where Sex = 'F')
select concat('1 : ',cast(ctem.male as float)/cast(ctef.female as float)) as ratio
from ctem,ctef

--7.Fetch the top 5 athletes who have won the most gold medals.


select Name, count(medal) as total_gold_medals
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
where Medal = 'Gold'
group by Name
having count(medal) in (select  distinct top 5 count(medal) 
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
where Medal = 'Gold'
group by Name
order by count(medal) desc) 
order by count(medal) desc



--8.Fetch the top 5 most successful countries in olympics. Success is defined by no of medals won.


with cte as
(
select  region , count(medal) as total_medals, 
rank () over (order by count(medal) desc) as rnk
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
where medal <> 'NA'
group by region 

)
select *
from cte 
where rnk <= 5


--9.List down total gold, silver and broze medals won by each country corresponding to each olympic games.


select g.Games,g.region, ggg as gold,sss as silver ,bbb as bronze
from 
(select e.Games,r.Region,
sum(case when medal = 'Gold' then 1 else 0 end) as ggg
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
group by games,region) as g
join
(select e.Games,r.Region,
sum(case when medal = 'Silver' then 1 else 0 end) as sss
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
group by games,region) as s on
g.Games = s.Games and g.region = s.region
join
(select e.Games,r.Region,
sum(case when medal = 'Bronze' then 1 else 0 end) as bbb
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
group by games,region) as b on
g.Games = b.Games and g.region = b.region





--10.Identify which country won the most gold, most silver and most bronze medals in each olympic games.


with cteg as
(select Games, region ,count(medal) as tot_gold,
rank () over (partition by games order by count(medal) desc) as rnk
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
where medal = 'Gold'
group by Games,region),
ctes as
(select Games, region ,count(medal) as tot_silver,
rank () over (partition by games order by count(medal) desc) as rnk
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
where medal = 'Silver'
group by Games,region),
cteb as
(select Games, region ,count(medal) as tot_bronze,
rank () over (partition by games order by count(medal) desc) as rnk
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
where medal = 'Bronze'
group by Games,region)
select g.Games, concat(g.region,' - ',tot_gold) as max_gold, 
				concat(s.region,' - ',tot_silver) as max_silver, 
				concat(b.region, ' - ',b.tot_bronze) as max_bronze
from cteg as g
join ctes as s
on g.games = s.Games
join cteb as b
on b.Games = g.Games
where g.rnk =1 and s.rnk = 1 and b.rnk = 1








--bonus 1.In which Sport/event, Georgia has won highest medals.

select top 1 Sport, count(medal) as total_medals
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
where region = 'Georgia' and medal <> 'NA'
group by Sport
order by count(Medal) desc


--bonus 2.Break down all olympic games where Gerogia won medal for Wrestling and how many medals in each olympic games.

select region,sport,games,count(medal) as total_medals
from SQL_Portfolio.dbo.athlete_events as e
join SQL_Portfolio.dbo.noc_regions as r on
e.NOC = r.NOC
where region = 'Georgia' and medal <> 'NA' and sport = 'Wrestling'
group by Sport,region,Games
order by count(medal) desc
